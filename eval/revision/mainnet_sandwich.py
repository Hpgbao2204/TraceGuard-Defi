"""RQ4 on mainnet: drop tests on historical sandwiches with the Go engine, in builder hindsight.

    python -m eval.revision.mainnet_sandwich scan    --start 22100000 --blocks 400 --max 40
    python -m eval.revision.mainnet_sandwich acquire
    python -m eval.revision.mainnet_sandwich run     --exe .cache/geth-replay.exe

scan     weak labels with the Qin/Torres heuristic on Uniswap V2 and V3 Swap events: in one block, a
         front-run and a back-run on the same pool, sent to the same contract (or from the same sender),
         in opposite directions, around a victim swap in the front-run's direction by another sender,
         with the back-run selling 90-110% of what the front-run bought. Needs an archive RPC (.env).
acquire  a proof-bound B2 context for every victim (prefix = all transactions before it, which
         includes the front-run). Needs the archive and trace RPC (.env).
run      three geth-replay runs per victim, all local: baseline (acceptance gate), drop of the
         front-run, and a placebo drop of a prefix transaction that emits no log of the attacked pool.
         The victim's output is the amount it receives from the attacked pool in its own Swap event, so
         native-ETH outputs are covered. The verdict follows Sect. 3.5 of the paper.

Outputs stay under .cache/revision/sandwich/ (local only).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / ".cache" / "revision" / "sandwich"
LABELS = WORK / "labels.json"
V2_SWAP = "0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822"
V3_SWAP = "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67"
DELTA = 0.001  # 10 bps of the victim's counterfactual output, as in the simulator


def _int(word: str, signed: bool = False) -> int:
    v = int(word, 16)
    if signed and v >= 1 << 255:
        v -= 1 << 256
    return v


def decode_swap(log: dict) -> tuple[bool, int, int] | None:
    """(zero_for_one, amount_in, amount_out) of a V2 or V3 Swap event, or None."""
    topics = log.get("topics") or []
    if not topics:
        return None
    data = log["data"][2:]
    words = [data[i:i + 64] for i in range(0, len(data), 64)]
    if topics[0] == V2_SWAP and len(words) >= 4:
        a0i, a1i, a0o, a1o = (_int(w) for w in words[:4])
        if a0i > 0 and a1o > 0:
            return True, a0i, a1o
        if a1i > 0 and a0o > 0:
            return False, a1i, a0o
        return None
    if topics[0] == V3_SWAP and len(words) >= 2:
        a0, a1 = _int(words[0], True), _int(words[1], True)
        if a0 > 0 > a1:
            return True, a0, -a1
        if a1 > 0 > a0:
            return False, a1, -a0
    return None


def pool_swaps(logs: list[dict]) -> dict[str, list[tuple[bool, int, int, str]]]:
    out: dict[str, list[tuple[bool, int, int, str]]] = {}
    for lg in logs:
        s = decode_swap(lg)
        if s:
            kind = "v2" if lg["topics"][0] == V2_SWAP else "v3"
            out.setdefault(lg["address"].lower(), []).append((*s, kind))
    return out


def find_sandwiches(block: dict, receipts: list[dict]) -> list[dict[str, Any]]:
    """Weak sandwich labels in one block (see module docstring)."""
    txs = block["transactions"]
    meta = [(t["from"].lower(), (t.get("to") or "").lower()) for t in txs]
    swaps = [pool_swaps(r.get("logs") or []) if int(r.get("status", "0x1"), 16) == 1 else {} for r in receipts]
    found, used = [], set()
    for a in range(len(txs)):
        for pool, sa in swaps[a].items():
            if len(sa) != 1 or a in used:
                continue
            dir_a, _, bought, kind = sa[0]
            for b in range(a + 2, min(len(txs), a + 40)):
                sb = swaps[b].get(pool)
                if not sb or len(sb) != 1 or sb[0][0] == dir_a:
                    continue
                same_bot = meta[a][1] == meta[b][1] and meta[a][1] != "" or meta[a][0] == meta[b][0]
                if not same_bot or not (0.9 <= sb[0][1] / max(bought, 1) <= 1.1):
                    continue
                victims = [v for v in range(a + 1, b)
                           if pool in swaps[v] and len(swaps[v][pool]) == 1 and swaps[v][pool][0][0] == dir_a
                           and meta[v][0] not in (meta[a][0], meta[b][0]) and meta[v][1] != meta[a][1]]
                if not victims:
                    continue
                v = victims[0]
                found.append({"block": int(block["number"], 16), "pool": pool, "kind": kind,
                              "front": a, "victim": v, "back": b, "victim_hash": txs[v]["hash"],
                              "front_hash": txs[a]["hash"], "back_hash": txs[b]["hash"],
                              "victim_out_obs": swaps[v][pool][0][2], "zero_for_one": dir_a})
                used.update((a, b))
                break
    return found


def _clients():
    from core.env import load_dotenv, resolve_rpc_candidates, resolve_trace_rpc_candidates
    from core.rpc import RpcClient
    load_dotenv()
    a, t = resolve_rpc_candidates("mainnet"), resolve_trace_rpc_candidates("mainnet")
    return (RpcClient(a[0], timeout=60, attempts=2, fallback_urls=a[1:]),
            RpcClient(t[0], timeout=90, attempts=2, fallback_urls=t[1:]))


def cmd_scan(args) -> None:
    archive, _ = _clients()
    labels: list[dict] = []
    for n in range(args.start, args.start + args.blocks):
        block = archive.call("eth_getBlockByNumber", [hex(n), True])
        receipts = archive.call("eth_getBlockReceipts", [hex(n)])
        labels += find_sandwiches(block, receipts)
        print(f"block {n}: {len(labels)} sandwiches so far", flush=True)
        if len(labels) >= args.max:
            break
    WORK.mkdir(parents=True, exist_ok=True)
    LABELS.write_text(json.dumps({"start": args.start, "heuristic": __doc__.split("scan", 1)[1].split("acquire")[0].strip(),
                                  "labels": labels[:args.max]}, indent=1), encoding="utf-8")
    print(f"wrote {LABELS}")


def ctx_dir(label: dict) -> Path:
    return WORK / "ctx" / label["victim_hash"]


def cmd_acquire(args) -> None:
    from eval.b2_proofs import acquire as acquire_proofs
    from eval.results.b2_context import acquire as acquire_context
    archive, trace = _clients()
    for lb in json.loads(LABELS.read_text(encoding="utf-8"))["labels"]:
        out = ctx_dir(lb)
        if (out / "prestate_proofs.json").is_file():
            continue
        t0 = time.perf_counter()
        try:
            acquire_context(archive, trace, tx_hash=lb["victim_hash"], block_number=lb["block"],
                            tx_index=lb["victim"], out=out, timeout_s=120.0)
            acquire_proofs(out, archive)
            print(f"{lb['victim_hash'][:12]} ok in {time.perf_counter() - t0:.0f} s", flush=True)
        except Exception as exc:  # keep going; the run step reports missing contexts
            print(f"{lb['victim_hash'][:12]} failed: {type(exc).__name__}: {str(exc)[:160]}", flush=True)


def run_engine(exe: str, ctx: Path, target: int, drop: list[int], out: Path) -> dict | None:
    cmd = [exe, "-context", str(ctx), "-proofs", str(ctx / "prestate_proofs.json"), "-target-index", str(target),
           "-lean", "-output", str(out)]
    for d in drop:
        cmd += ["-drop-tx", str(d)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if proc.returncode != 0 or not out.is_file():
        out.with_suffix(".stderr.txt").write_text((proc.stderr or proc.stdout)[-4000:], encoding="utf-8")
        return None
    return json.loads(out.read_text(encoding="utf-8"))


def victim_output(payload: dict, target: int, pool: str) -> int | None:
    for r in payload.get("per_tx") or []:
        if r.get("index") == target:
            if not r.get("actual_status"):
                return None
            got = [s[2] for s in pool_swaps(r.get("logs") or []).get(pool, [])]
            return sum(got) if got else 0
    return None


def classify(payload: dict | None, target: int, pool: str, out_obs: int) -> dict[str, Any]:
    if payload is None:
        return {"verdict": "INCONCLUSIVE", "reason": "engine_error"}
    o = payload.get("ordering_intervention") or {}
    rec: dict[str, Any] = {"confounds": o.get("ordering_confounds") or [],
                           "target_evm_ms": (payload.get("timing_ms") or {}).get("target_evm")}
    if o.get("fail_closed"):
        return {**rec, "verdict": "INCONCLUSIVE", "reason": "fail_closed",
                "fail_closed_reasons": (o.get("fail_closed_reasons") or [])[:5]}
    out_cf = victim_output(payload, target, pool)
    if out_cf is None:
        return {**rec, "verdict": "INCONCLUSIVE", "reason": "victim_reverted"}
    if not o.get("comparable"):
        return {**rec, "verdict": "INCONCLUSIVE", "reason": "incomparable", "detail": o.get("incomparable_reason")}
    harm = out_cf - out_obs
    rec.update(out_cf=out_cf, shortfall=harm, shortfall_rel=harm / out_cf if out_cf else None)
    if rec["confounds"]:
        return {**rec, "verdict": "INCONCLUSIVE", "reason": "ordering_confound"}
    return {**rec, "verdict": "CAUSE" if harm >= DELTA * out_cf else "NO_EFFECT", "reason": None}


def placebo_index(label: dict, ctx: Path) -> int | None:
    """Latest prefix transaction before the victim that emits no log of the attacked pool and is not the bot's."""
    receipts = json.loads((ctx / "receipts.json").read_text(encoding="utf-8"))
    txs = json.loads((ctx / "transactions.json").read_text(encoding="utf-8"))
    txs = txs if isinstance(txs, list) else txs.get("transactions", [])
    bot = {txs[label["front"]]["from"].lower(), (txs[label["front"]].get("to") or "").lower()}
    for rec in sorted(receipts, key=lambda r: -r["index"]):
        i, rc = rec["index"], rec["receipt"]
        if i >= label["victim"] or i == label["front"]:
            continue
        if any(lg["address"].lower() == label["pool"] for lg in rc.get("logs") or []):
            continue
        if txs[i]["from"].lower() in bot or (txs[i].get("to") or "").lower() in bot:
            continue
        return i
    return None


def cmd_run(args) -> None:
    exe = str(Path(args.exe).resolve())
    labels = json.loads(LABELS.read_text(encoding="utf-8"))["labels"]
    rows = []
    for lb in labels:
        ctx, v, pool = ctx_dir(lb), lb["victim"], lb["pool"]
        row: dict[str, Any] = {k: lb[k] for k in ("block", "pool", "kind", "front", "victim", "back", "victim_hash")}
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
        row["front_drop"] = classify(run_engine(exe, ctx, v, [lb["front"]], runs / "drop_front.json"), v, pool, out_obs)
        p = placebo_index(lb, ctx)
        row["placebo_index"] = p
        row["placebo_drop"] = (classify(run_engine(exe, ctx, v, [p], runs / "drop_placebo.json"), v, pool, out_obs)
                               if p is not None else {"verdict": "N/A", "reason": "no_placebo_candidate"})
        rows.append(row)
        print(f"{lb['victim_hash'][:12]} {lb['kind']} front={row['front_drop']['verdict']}"
              f"({row['front_drop'].get('reason')}) placebo={row['placebo_drop']['verdict']}", flush=True)
    summary = summarize(rows)
    (WORK / "results.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))


def summarize(rows: list[dict]) -> dict[str, Any]:
    from collections import Counter
    ok = [r for r in rows if r.get("status") == "ok"]
    s: dict[str, Any] = {"labels": len(rows), "status": dict(Counter(r.get("status") for r in rows)),
                         "baseline_output_matches_receipt": sum(bool(r.get("out_obs_matches_receipt")) for r in ok)}
    for key in ("front_drop", "placebo_drop"):
        s[key] = dict(Counter(f"{r[key]['verdict']}" + (f"({r[key]['reason']})" if r[key].get("reason") else "")
                              for r in ok))
        for kind in ("v2", "v3"):
            s[f"{key}_{kind}"] = dict(Counter(r[key]["verdict"] for r in ok if r["kind"] == kind))
    rel = sorted(r["front_drop"]["shortfall_rel"] for r in ok
                 if r["front_drop"]["verdict"] == "CAUSE" and r["front_drop"].get("shortfall_rel") is not None)
    s["cause_shortfall_rel_median"] = rel[len(rel) // 2] if rel else None
    ms = sorted(r["front_drop"]["target_evm_ms"] for r in ok if r["front_drop"].get("target_evm_ms") is not None)
    s["target_evm_ms_median"] = ms[len(ms) // 2] if ms else None
    return s


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sc = sub.add_parser("scan")
    sc.add_argument("--start", type=int, default=22100000)
    sc.add_argument("--blocks", type=int, default=400)
    sc.add_argument("--max", type=int, default=40)
    sub.add_parser("acquire")
    rn = sub.add_parser("run")
    rn.add_argument("--exe", default=str(ROOT / ".cache" / "geth-replay.exe"))
    args = ap.parse_args()
    {"scan": cmd_scan, "acquire": cmd_acquire, "run": cmd_run}[args.cmd](args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
