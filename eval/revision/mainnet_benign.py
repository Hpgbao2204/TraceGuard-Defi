"""RQ4 on mainnet: drop tests on heuristic-negative bundles with a sandwich-like shape (benign cohort).

    python -m eval.revision.mainnet_benign scan     # same 189 blocks as the sandwiches, needs archive RPC
    python -m eval.revision.mainnet_benign acquire  # proof-bound context per user swap
    python -m eval.revision.mainnet_benign run --exe .cache/geth-replay.exe

scan     In the blocks of the sandwich labels (22,100,000 to 22,100,188), every successful transaction with
         exactly one Uniswap V2/V3 Swap is a user swap U on pool P. Stage 1 flags, for U, the transactions
         before it that touch P; the candidate D is the nearest one from another sender. The pair is kept
         only if the sandwich heuristic of mainnet_sandwich does not label it (U is no labeled victim, and D
         is no labeled front-run or back-run), so the cohort is what a builder policy would test besides
         sandwiches. D is typed by its shape on P, first match wins:
           jit          D mints or burns liquidity on P (V2 Mint/Burn, V3 Mint/Burn);
           multihop     D swaps on two or more pools (router, aggregator, arbitrage route);
           backrun      D swaps on P against U's direction (arbitrage and back-run shape);
           same_dir     D swaps on P in U's direction without a matching back-run (front-run shape).
         At most --per-shape pairs per shape, in block order, one per user swap.
acquire  as mainnet_sandwich: a B2 context for U, whose prefix contains D.
run      baseline and drop of D on the Go engine, verdict as for the sandwiches (delta = 10 bps).

Outputs stay under .cache/revision/benign/ (local only).
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from eval.revision.mainnet_sandwich import LABELS as SANDWICH_LABELS
from eval.revision.mainnet_sandwich import (
    _clients,
    classify,
    pool_swaps,
    run_engine,
    victim_output,
)

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / ".cache" / "revision" / "benign"
LABELS = WORK / "labels.json"
SHAPES = ("jit", "multihop", "backrun", "same_dir")
LIQUIDITY_TOPICS = {
    "0x4c209b5fc8ad50758f13e2e1088ba56a560dff690a1c6fef26394f4c03821c4f",  # V2 Mint
    "0xdccd412f0b1252819cb1fd330b93224ca42612892bb3f4f789976e6d81936496",  # V2 Burn
    "0x7a53080ba414158be7ec69b987b5fb7d07dee101fe85488f0853ae16239d0bde",  # V3 Mint
    "0x0c396cd989a39f4459b5fa1aed6a9a8dcdbc45908acfd67e028cd568da98982c",  # V3 Burn
}


def shape_of(d_logs: list[dict], d_swaps: dict, pool: str, u_dir: bool) -> str | None:
    if any(lg["address"].lower() == pool and (lg.get("topics") or [""])[0] in LIQUIDITY_TOPICS for lg in d_logs):
        return "jit"
    if pool not in d_swaps:
        return None
    if len(d_swaps) >= 2:
        return "multihop"
    return "backrun" if d_swaps[pool][0][0] != u_dir else "same_dir"


def find_pairs(block: dict, receipts: list[dict], taken: set[tuple[int, int]]) -> list[dict[str, Any]]:
    txs = block["transactions"]
    ok = [int(r.get("status", "0x1"), 16) == 1 for r in receipts]
    swaps = [pool_swaps(r.get("logs") or []) if ok[i] else {} for i, r in enumerate(receipts)]
    n = int(block["number"], 16)
    out = []
    for u in range(len(txs)):
        if len(swaps[u]) != 1:
            continue
        (pool, su), = swaps[u].items()
        if len(su) != 1 or (n, u) in taken:
            continue
        u_dir, _, u_out, kind = su[0]
        for d in range(u - 1, -1, -1):
            if not ok[d] or txs[d]["from"].lower() == txs[u]["from"].lower():
                continue
            shape = shape_of(receipts[d].get("logs") or [], swaps[d], pool, u_dir)
            if shape is None:
                continue
            if (n, d) in taken:
                break  # the nearest pool-touching transaction belongs to a labeled sandwich
            out.append({"block": n, "pool": pool, "kind": kind, "shape": shape, "d": d, "victim": u,
                        "victim_hash": txs[u]["hash"], "d_hash": txs[d]["hash"], "victim_out_obs": u_out,
                        "zero_for_one": u_dir})
            break
    return out


def cmd_scan(args) -> None:
    sw = json.loads(SANDWICH_LABELS.read_text(encoding="utf-8"))
    blocks = range(sw["start"], max(lb["block"] for lb in sw["labels"]) + 1)
    taken = {(lb["block"], lb[k]) for lb in sw["labels"] for k in ("front", "victim", "back")}
    archive, _ = _clients()
    pairs: list[dict] = []
    for n in blocks:
        block = archive.call("eth_getBlockByNumber", [hex(n), True])
        receipts = archive.call("eth_getBlockReceipts", [hex(n)])
        pairs += find_pairs(block, receipts, taken)
    counts = {s: sum(p["shape"] == s for p in pairs) for s in SHAPES}
    chosen = [p for s in SHAPES for p in [q for q in pairs if q["shape"] == s][:args.per_shape]]
    WORK.mkdir(parents=True, exist_ok=True)
    LABELS.write_text(json.dumps({"blocks": [blocks.start, blocks.stop - 1], "candidates_by_shape": counts,
                                  "per_shape": args.per_shape, "labels": chosen}, indent=1), encoding="utf-8")
    print(f"{len(pairs)} candidate pairs in {len(blocks)} blocks {counts}; kept {len(chosen)}")


def ctx_dir(label: dict) -> Path:
    return WORK / "ctx" / label["victim_hash"]


def cmd_acquire(args) -> None:
    from eval.b2_proofs import acquire as acquire_proofs
    from eval.results.b2_context import acquire as acquire_context
    archive, trace = _clients()
    i, n = (int(x) for x in args.shard.split("/"))
    for k, lb in enumerate(json.loads(LABELS.read_text(encoding="utf-8"))["labels"]):
        if k % n != i:
            continue
        out = ctx_dir(lb)
        if (out / "prestate_proofs.json").is_file():
            continue
        t0 = time.perf_counter()
        try:
            if not (out / "prestates.json").is_file():
                acquire_context(archive, trace, tx_hash=lb["victim_hash"], block_number=lb["block"],
                                tx_index=lb["victim"], out=out, timeout_s=120.0)
            acquire_proofs(out, archive)
            print(f"{lb['victim_hash'][:12]} ok in {time.perf_counter() - t0:.0f} s", flush=True)
        except Exception as exc:  # noqa: BLE001 - keep going; the run step reports missing contexts
            print(f"{lb['victim_hash'][:12]} failed: {type(exc).__name__}: {str(exc)[:160]}", flush=True)


def wilson(k: int, n: int, z: float = 1.959964) -> list[float] | None:
    if n == 0:
        return None
    p, d = k / n, 1 + z * z / n
    c, h = (p + z * z / (2 * n)) / d, z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return [c - h, c + h]


def summarize(rows: list[dict]) -> dict[str, Any]:
    from collections import Counter
    ok = [r for r in rows if r.get("status") == "ok"]
    s: dict[str, Any] = {"pairs": len(rows), "status": dict(Counter(r.get("status") for r in rows)),
                         "baseline_output_matches_receipt": sum(bool(r.get("out_obs_matches_receipt")) for r in ok)}
    verdicts = Counter(r["drop"]["verdict"] for r in ok)
    s["drop"] = dict(Counter(r["drop"]["verdict"] + (f"({r['drop']['reason']})" if r["drop"].get("reason") else "")
                             for r in ok))
    s["rates"] = {v: {"k": verdicts[v], "n": len(ok), "rate": verdicts[v] / len(ok) if ok else None,
                      "wilson95": wilson(verdicts[v], len(ok))} for v in ("CAUSE", "NO_EFFECT", "INCONCLUSIVE")}
    s["by_shape"] = {sh: dict(Counter(r["drop"]["verdict"] for r in ok if r["shape"] == sh)) for sh in SHAPES}
    s["cause_shortfall_rel"] = sorted(r["drop"]["shortfall_rel"] for r in ok
                                      if r["drop"]["verdict"] == "CAUSE" and r["drop"].get("shortfall_rel") is not None)
    return s


def cmd_run(args) -> None:
    exe = str(Path(args.exe).resolve())
    labels = json.loads(LABELS.read_text(encoding="utf-8"))["labels"]
    rows = []
    for lb in labels:
        ctx, v, pool = ctx_dir(lb), lb["victim"], lb["pool"]
        row: dict[str, Any] = {k: lb[k] for k in ("block", "pool", "kind", "shape", "d", "victim", "victim_hash")}
        if not (ctx / "prestate_proofs.json").is_file():
            rows.append({**row, "status": "no_context"})
            continue
        runs = WORK / "runs" / lb["victim_hash"]
        runs.mkdir(parents=True, exist_ok=True)
        base = run_engine(exe, ctx, v, [], runs / "base.json")
        if base is None or not base.get("acceptance_gate"):
            rows.append({**row, "status": "replay_gate_failed"})
            continue
        out_obs = victim_output(base, v, pool)
        row.update(status="ok", out_obs=out_obs, out_obs_matches_receipt=out_obs == lb["victim_out_obs"])
        row["drop"] = classify(run_engine(exe, ctx, v, [lb["d"]], runs / "drop.json"), v, pool, out_obs)
        rows.append(row)
        print(f"{lb['victim_hash'][:12]} {lb['shape']} {lb['kind']} drop={row['drop']['verdict']}"
              f"({row['drop'].get('reason')}) rel={row['drop'].get('shortfall_rel')}", flush=True)
    summary = summarize(rows)
    (WORK / "results.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))


def cmd_audit(_args) -> None:
    """For every CAUSE, look for a later transaction in the block that trades the pool against D's direction
    from D's sender or to D's contract: a back-run the sandwich heuristic rejected (size rule, 40-tx window,
    or a different victim), which would make D a missed sandwich front-run rather than benign order flow."""
    archive, _ = _clients()
    res = json.loads((WORK / "results.json").read_text(encoding="utf-8"))
    labels = {lb["victim_hash"]: lb for lb in json.loads(LABELS.read_text(encoding="utf-8"))["labels"]}
    audit = {}
    for r in res["rows"]:
        if r.get("status") != "ok" or r["drop"]["verdict"] != "CAUSE":
            continue
        lb = labels[r["victim_hash"]]
        block = archive.call("eth_getBlockByNumber", [hex(lb["block"]), True])
        receipts = archive.call("eth_getBlockReceipts", [hex(lb["block"])])
        txs = block["transactions"]
        d_from, d_to = txs[lb["d"]]["from"].lower(), (txs[lb["d"]].get("to") or "").lower()
        d_sw = pool_swaps(receipts[lb["d"]].get("logs") or []).get(lb["pool"]) or []
        d_dir = d_sw[0][0] if d_sw else None
        later = []
        for j in range(lb["victim"] + 1, len(txs)):
            sj = pool_swaps(receipts[j].get("logs") or []).get(lb["pool"]) or []
            if (sj and d_dir is not None and sj[0][0] != d_dir
                    and (txs[j]["from"].lower() == d_from or (txs[j].get("to") or "").lower() == d_to)):
                later.append({"index": j, "size_ratio": sj[0][1] / max(d_sw[0][2], 1)})
        audit[r["victim_hash"]] = {"shape": lb["shape"], "shortfall_rel": r["drop"]["shortfall_rel"],
                                   "d_direction_on_pool": d_dir, "possible_backruns": later}
        print(r["victim_hash"][:12], lb["shape"], f"{r['drop']['shortfall_rel']:.4f}", later[:3], flush=True)
    res["summary"]["cause_audit"] = audit
    res["summary"]["cause_with_possible_backrun"] = sum(bool(v["possible_backruns"]) for v in audit.values())
    (WORK / "results.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(f"{res['summary']['cause_with_possible_backrun']} of {len(audit)} CAUSE have a possible back-run")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sc = sub.add_parser("scan")
    sc.add_argument("--per-shape", type=int, default=15)
    aq = sub.add_parser("acquire")
    aq.add_argument("--shard", default="0/1", help="i/n: acquire every n-th label starting at i (parallel runs)")
    rn = sub.add_parser("run")
    rn.add_argument("--exe", default=str(ROOT / ".cache" / "geth-replay.exe"))
    sub.add_parser("audit")
    args = ap.parse_args()
    {"scan": cmd_scan, "acquire": cmd_acquire, "run": cmd_run, "audit": cmd_audit}[args.cmd](args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
