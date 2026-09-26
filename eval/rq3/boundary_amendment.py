"""Mechanical amendment of the frozen fixed-20 victim boundaries (published alongside the frozen manifest).

    python -m eval.rq3.boundary_amendment            # writes eval/rq3/fixed20_cases_amended.json

The frozen manifest ``fixed20_cases.json`` stays unchanged. The amended manifest applies one rule to all
20 cases, using only the transaction, its receipt, its call trace, and chain history (no incident labels):

Attacker set M
  M1  the frozen attacker addresses and ``tx.from``;
  M2  every contract created inside the target transaction T (CREATE/CREATE2 frames);
  M3  every contract in ``{tx.to} ∪ V`` deployed within W = 7,200 blocks (about one day) before the attack
      block in a block that contains a transaction sent by ``tx.from``;
  M4  ``tx.to``, unless it was deployed more than W blocks before the attack (an established contract that
      the attacker called directly, e.g. a drained pool, is not the attacker's entry contract).
Victim boundary V' = (V \\ M) ∪ O ∪ P ∪ F
  O   outflow victims: every account o ∉ M, o ≠ 0x0, o ≠ WETH (an unwrap pays out native ETH but is not a
      loss), with a net outflow of at least one asset in T (ERC-20 Transfer logs and native value
      transfers) and a net inflow of none;
  P   allowance victims: for every successful ``transferFrom(o, ., .)`` CALL in T made by a contract c with
      o ∉ M, c ∉ M, o ≠ c, the owner o, and the spender c if c was called by an address in M;
  F   protocol contracts: every contract c ∉ M called by an address in M that had code before T and was
      deployed by the same externally owned account as a contract already in (V \\ M) ∪ O ∪ P.

The call trace comes from a debug tracer and is untrusted input for the boundary only; replay results
still come from proof-checked state. Deployment blocks come from binary search over ``eth_getCode`` on the
archive endpoint and deployers from ``trace_block`` on the trace endpoint. All lookups are cached under
.cache/rq3_amend/.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
FROZEN = ROOT / "eval" / "rq3" / "fixed20_cases.json"
AMENDED = ROOT / "eval" / "rq3" / "fixed20_cases_amended.json"
CONTEXTS = ROOT / "eval" / "results" / "m4" / "b2-contexts-fresh"
CACHE = ROOT / ".cache" / "rq3_amend"
W = 7200
TRANSFER_FROM = "0x23b872dd"
ZERO = "0x" + "0" * 40
WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"


def _retry(fn, *args, attempts: int = 8):
    delay = 2.0
    for i in range(attempts):
        try:
            return fn(*args)
        except Exception:  # rate limits and transient TLS errors
            if i == attempts - 1:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 60)


def _cached(name: str, fn):
    path = CACHE / name
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    value = fn()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return value


def _clients():
    from core.env import load_dotenv, resolve_rpc_candidates, resolve_trace_rpc_candidates
    from core.rpc import RpcClient
    load_dotenv()
    a, t = resolve_rpc_candidates("mainnet"), resolve_trace_rpc_candidates("mainnet")
    return RpcClient(a[0], timeout=60, attempts=2), RpcClient(t[0], timeout=180, attempts=2)


def deployment(archive, address: str, before: int) -> dict[str, Any]:
    """First block with code at ``address`` (binary search), and the senders of that block's transactions."""
    def search():
        if _retry(archive.call, "eth_getCode", [address, hex(before)]) in ("0x", None):
            return {"block": None}
        lo, hi = 0, before
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if _retry(archive.call, "eth_getCode", [address, hex(mid)]) not in ("0x", None):
                hi = mid
            else:
                lo = mid
        blk = _retry(archive.call, "eth_getBlockByNumber", [hex(hi), True])
        return {"block": hi, "senders": sorted({t["from"].lower() for t in blk["transactions"]})}
    return _cached(f"deploy-{address.lower()}.json", search)


def deployer(archive, trace, address: str, before: int) -> str | None:
    """Externally owned account that sent the transaction creating ``address`` (via trace_block)."""
    d = deployment(archive, address, before)
    if d.get("block") is None:
        return None

    def find():
        traces = _retry(trace.call, "trace_block", [hex(d["block"])]) or []
        traces = [t for t in traces if t.get("transactionHash")]  # block rewards carry no transaction
        roots = {t["transactionHash"]: t["action"].get("from", "").lower()
                 for t in traces if not t.get("traceAddress")}
        for t in traces:
            if t.get("type") == "create" and ((t.get("result") or {}).get("address") or "").lower() == address:
                return {"deployer": roots.get(t["transactionHash"])}
        return {"deployer": None}
    return _cached(f"deployer-{address.lower()}.json", find)["deployer"]


def walk(frame: dict, parent_failed: bool = False, parent: dict | None = None):
    """(frame, failed, parent frame) for every frame; a frame fails if it or an ancestor reverted."""
    failed = parent_failed or bool(frame.get("error"))
    yield frame, failed, parent
    for child in frame.get("calls") or []:
        yield from walk(child, failed, frame)


def net_flows(receipt: dict, frames) -> dict[str, dict[str, int]]:
    """Per account and asset: inflow minus outflow in T (ERC-20 Transfer logs and native value)."""
    flows: dict[str, dict[str, int]] = {}

    def add(acct: str, asset: str, v: int) -> None:
        flows.setdefault(acct, {}).setdefault(asset, 0)
        flows[acct][asset] += v
    for lg in receipt.get("logs") or []:
        t = lg.get("topics") or []
        if len(t) == 3 and t[0].lower().startswith("0xddf252ad") and lg.get("data", "0x") != "0x":
            src, dst, v = "0x" + t[1][-40:].lower(), "0x" + t[2][-40:].lower(), int(lg["data"][:66], 16)
            add(src, lg["address"].lower(), -v)
            add(dst, lg["address"].lower(), v)
    for f, failed, _ in frames:
        v = int(f.get("value") or "0x0", 16)
        if v and not failed and f.get("type") in ("CALL", "CREATE", "CREATE2") and f.get("to"):
            add(f["from"].lower(), "native", -v)
            add(f["to"].lower(), "native", v)
    return flows


def amend_case(name: str, case: dict, archive, trace) -> dict[str, Any]:
    ctx = CONTEXTS / name
    txs = json.loads((ctx / "transactions.json").read_text(encoding="utf-8"))
    tx = txs[case["tx_index"]]
    sender, to = tx["from"].lower(), (tx.get("to") or "").lower()
    block = int(case["block"])
    receipts = json.loads((ctx / "receipts.json").read_text(encoding="utf-8"))
    receipt = next(r["receipt"] for r in receipts if r["receipt"]["transactionHash"].lower() == case["tx_hash"].lower())
    tr = _cached(f"calltrace-{case['tx_hash']}.json",
                 lambda: _retry(trace.call, "debug_traceTransaction", [case["tx_hash"], {"tracer": "callTracer"}]))
    frames = list(walk(tr))
    created = {f["to"].lower() for f, failed, _ in frames if f.get("type", "").startswith("CREATE") and not failed
               and f.get("to")}
    frozen_v = [v.lower() for v in case["victim"]]
    m: dict[str, str] = {a.lower(): "M1 frozen attacker" for a in case["attacker"]}
    m.setdefault(sender, "M1 tx.from")
    for c in created:
        m.setdefault(c, "M2 created in T")
    deploys: dict[str, Any] = {}
    for c in sorted({to, *frozen_v} - {""} - created):
        d = deployment(archive, c, block - 1)
        deploys[c] = d.get("block")
        if d.get("block") is None:
            continue
        recent = block - d["block"] <= W
        if recent and sender in d.get("senders", []):
            m.setdefault(c, f"M3 deployed {block - d['block']} blocks before the attack in a block with a tx from tx.from")
        elif c == to and recent:
            m.setdefault(c, f"M4 tx.to deployed {block - d['block']} blocks before the attack")
    if to and to not in m and deploys.get(to) is None:
        m.setdefault(to, "M4 tx.to without code before the attack")

    reasons: dict[str, str] = {}
    flows = net_flows(receipt, frames)
    for acct, per in flows.items():
        if acct in m or acct in (ZERO, WETH):
            continue
        if any(v < 0 for v in per.values()) and not any(v > 0 for v in per.values()):
            reasons.setdefault(acct, "O net outflow, no net inflow")
    for f, failed, parent in frames:
        inp = (f.get("input") or "").lower()
        if failed or f.get("type") != "CALL" or not inp.startswith(TRANSFER_FROM) or len(inp) < 10 + 64:
            continue
        owner, spender = "0x" + inp[10 + 24:10 + 64], f["from"].lower()
        if owner in m or spender in m or owner == spender:
            continue
        reasons.setdefault(owner, "P allowance spent by " + spender)
        if (parent or {}).get("from", "").lower() in m:
            reasons.setdefault(spender, "P spender called by the attacker")
    base = {v for v in frozen_v if v not in m} | set(reasons)
    deployers = {}
    for v in sorted(base):
        if deployment(archive, v, block - 1).get("block") is not None:
            deployers[v] = deployer(archive, trace, v, block - 1)
    family = {d for d in deployers.values() if d}
    called = {f["to"].lower() for f, failed, _ in frames
              if not failed and f.get("type") == "CALL" and f["from"].lower() in m and f.get("to")}
    for c in sorted(called - m.keys() - base):
        if deployment(archive, c, block - 1).get("block") is None:
            continue
        dep = deployer(archive, trace, c, block - 1)
        if dep and dep in family:
            reasons.setdefault(c, f"F same deployer {dep[:10]} as the victim protocol")
    new_v = sorted(base | {c for c, r in reasons.items() if r.startswith("F ")})
    return {"victim": new_v, "attacker": sorted(m), "tx_index": case["tx_index"], "block": case["block"],
            "tx_hash": case["tx_hash"],
            "amendment": {"removed_from_v": {v: m[v] for v in frozen_v if v in m},
                          "added_to_v": {v: reasons[v] for v in new_v if v not in frozen_v},
                          "tx_to": to, "created_in_t": sorted(created), "deployment_blocks": deploys,
                          "changed": sorted(new_v) != sorted(frozen_v)}}


def main() -> int:
    frozen = json.loads(FROZEN.read_text(encoding="utf-8"))
    archive, trace = _clients()
    cases = {}
    for name, case in frozen["cases"].items():
        cases[name] = amend_case(name, case, archive, trace)
        a = cases[name]["amendment"]
        print(f"{name[13:45]:34s} removed={list(a['removed_from_v'])} added={list(a['added_to_v'])}", flush=True)
    doc = {"schema": 1, "source": "mechanical amendment of fixed20_cases.json; see eval/rq3/boundary_amendment.py",
           "frozen_manifest": FROZEN.name, "window_blocks": W,
           "rule": __doc__.split("Attacker set M", 1)[1].split("The call trace", 1)[0].strip(), "cases": cases}
    AMENDED.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    changed = [n for n, c in cases.items() if c["amendment"]["changed"]]
    print(f"wrote {AMENDED}; {len(changed)} of {len(cases)} boundaries changed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
