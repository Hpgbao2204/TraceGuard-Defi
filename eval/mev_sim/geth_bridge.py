"""Layer 2 on the paper's replay engine: anvil block -> B2 context -> ``geth-replay -drop-tx -lean``.

For a flagged bundle the builder mines the bundle as one anvil block on the current block prefix,
and this module exports that block in the same B2 context layout the mainnet cases use
(``block.json``, ``transactions.json``, ``receipts.json``, ``prestates.json``, ``poststates.json``,
``prestate_proofs.json`` with EIP-1186 proofs against the parent state root, ``ancestors.json``).
geth-replay then runs twice with ``-chain-id 31337 -lean -target-index <victim>``:

1. baseline (no intervention): the RQ2 fidelity gate. ``acceptance_gate`` must be true, i.e. the
   proof-bound replay reproduces status, gas, logs and relevant post-state of every transaction;
   otherwise the verdict is ``INCONCLUSIVE(replay_gate_failed)``;
2. ``-drop-tx <layer-1 suspects>``: the ordering intervention of M1. The engine's own report decides
   comparability: fail-closed on an unauthenticated read (``INCONCLUSIVE(fail_closed)``), victim
   reverts without the drop set or an intermediate transaction changes status, gas or logs
   (``INCONCLUSIVE(ordering_confound)``), anything else incomparable (``INCONCLUSIVE(incomparable)``).

Harm is the victim's net inflow of its output token in the counterfactual minus the baseline, read
from the engine's target logs, with the same thresholds and policy as ``detection.layer2``.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from .chain import CHAIN_ID, Receipt, Rpc
from .detection import CAUSE, INCONCLUSIVE, NO_EFFECT, Thresholds, Verdict, net_inflow

REPO = Path(__file__).resolve().parents[2]
DEFAULT_BINARY = REPO / "tools" / "geth-replay" / ("geth-replay.exe" if os.name == "nt" else "geth-replay")
HEADER_DROP = ("transactions", "uncles", "size", "totalDifficulty")


def find_geth_replay(explicit: str | None = None) -> str | None:
    for cand in (explicit, os.environ.get("GETH_REPLAY"), str(DEFAULT_BINARY), shutil.which("geth-replay")):
        if cand and Path(cand).is_file():
            return cand
    return None


def _slot(key) -> str:
    return f"0x{int(key, 16):064x}"


def _write(path: Path, value) -> None:
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def _batch(rpc: Rpc, calls: list[tuple[str, list]]) -> list:
    if not calls:
        return []
    payload = [{"jsonrpc": "2.0", "id": i, "method": m, "params": p} for i, (m, p) in enumerate(calls)]
    body = rpc.session.post(rpc.url, json=payload, timeout=120).json()
    out = [None] * len(calls)
    for item in body:
        if "error" in item:
            raise RuntimeError(f"{calls[item['id']][0]}: {item['error']}")
        out[item["id"]] = item["result"]
    return out


def _header(block: dict) -> dict:
    return {k: v for k, v in block.items() if k not in HEADER_DROP}


def _collect(accounts: dict[str, set[str]], state: dict) -> None:
    for address, value in (state or {}).items():
        slots = accounts.setdefault(address.lower(), set())
        for key in (value or {}).get("storage") or {}:
            slots.add(_slot(key))


def _creates(trace, accounts: dict[str, set[str]]) -> None:
    if isinstance(trace, dict):
        if str(trace.get("type", "")).upper() in ("CREATE", "CREATE2") and trace.get("to"):
            accounts.setdefault(trace["to"].lower(), set())
        for v in trace.values():
            _creates(v, accounts)
    elif isinstance(trace, list):
        for v in trace:
            _creates(v, accounts)


def export_context(rpc: Rpc, number: int, out: Path, target: int | None = None) -> dict:
    """Write the B2 context of anvil block ``number`` into ``out``: the block header and, as in the
    mainnet contexts, only the prefix and the target (transactions ``0..target``)."""
    out.mkdir(parents=True, exist_ok=True)
    block = rpc.call("eth_getBlockByNumber", [hex(number), True])
    txs = block["transactions"] if target is None else block["transactions"][: target + 1]
    hashes = [t["hash"] for t in txs]
    receipts = _batch(rpc, [("eth_getTransactionReceipt", [h]) for h in hashes])
    pre = _batch(rpc, [("debug_traceTransaction", [h, {"tracer": "prestateTracer"}]) for h in hashes])
    diff = _batch(rpc, [("debug_traceTransaction", [h, {"tracer": "prestateTracer",
                                                          "tracerConfig": {"diffMode": True}}]) for h in hashes])
    calls = _batch(rpc, [("debug_traceTransaction", [h, {"tracer": "callTracer"}]) for h in hashes])
    first = max(0, number - 256)
    ancestors = _batch(rpc, [("eth_getBlockByNumber", [hex(n), False]) for n in range(number - 1, first - 1, -1)])

    accounts: dict[str, set[str]] = {}
    for i in range(len(txs)):
        _collect(accounts, pre[i])
        _collect(accounts, diff[i].get("pre"))
        _collect(accounts, diff[i].get("post"))
        _creates(calls[i], accounts)
    parent = hex(number - 1)
    order = sorted(accounts)
    proofs = _batch(rpc, [("eth_getProof", [a, sorted(accounts[a]), parent]) for a in order])
    codes = _batch(rpc, [("eth_getCode", [a, parent]) for a in order])
    proof_file = {
        "schema_version": 3,
        "header": {"number": parent, "hash": ancestors[0]["hash"], "stateRoot": ancestors[0]["stateRoot"]},
        "proofs": [{"address": a, "code": c, "storage_keys": sorted(accounts[a]), "proof": p}
                   for a, c, p in zip(order, codes, proofs)],
    }
    _write(out / "block.json", _header(block))
    _write(out / "transactions.json", txs)
    _write(out / "receipts.json", [{"index": i, "tx_hash": h, "receipt": r} for i, (h, r) in enumerate(zip(hashes, receipts))])
    _write(out / "prestates.json", [{"index": i, "tx_hash": h, "trace": t} for i, (h, t) in enumerate(zip(hashes, pre))])
    _write(out / "poststates.json", [{"index": i, "tx_hash": h, "prestate": d.get("pre") or {},
                                      "poststate": d.get("post") or {}, "calltrace": c}
                                     for i, (h, d, c) in enumerate(zip(hashes, diff, calls))])
    _write(out / "prestate_proofs.json", proof_file)
    _write(out / "ancestors.json", [_header(a) for a in ancestors])
    return {"block": number, "txs": len(txs), "proof_accounts": len(order),
            "proof_slots": sum(len(s) for s in accounts.values())}


@dataclass
class GethRun:
    ok: bool
    out: dict = field(default_factory=dict)
    error: str = ""
    wall_ms: float = 0.0


def run_geth(binary: str, ctx: Path, target: int, drop: list[int] | None, out: Path) -> GethRun:
    cmd = [binary, "-context", str(ctx), "-proofs", str(ctx / "prestate_proofs.json"), "-chain-id", str(CHAIN_ID),
           "-target-index", str(target), "-lean", "-output", str(out)]
    for d in drop or []:
        cmd += ["-drop-tx", str(d)]
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    wall = (time.perf_counter() - t0) * 1e3
    if proc.returncode != 0 or not out.is_file():
        return GethRun(False, error=(proc.stderr or proc.stdout)[-400:], wall_ms=wall)
    return GethRun(True, json.loads(out.read_text()), wall_ms=wall)


def _target(out: dict, target: int) -> dict | None:
    for r in out.get("per_tx") or []:
        if r["index"] == target:
            return r
    return None


def _receipt(r: dict) -> Receipt:
    logs = [{"address": lg["address"], "topics": lg["topics"], "data": lg["data"]} for lg in r.get("logs") or []]
    return Receipt(1 if r.get("actual_status") else 0, logs, r.get("actual_gas", 0))


@dataclass
class GethVerdict:
    verdict: Verdict
    context: dict
    baseline_gate: bool
    timing: dict                     # engine timing_ms of the drop run and process wall time of both runs
    confound_kinds: list[str] = field(default_factory=list)
    incomparable: str = ""


def classify_drop_run(out: dict, vi: int, token: str, out_obs: int, victim_sender: str, pools: set[str],
                      thr: Thresholds) -> tuple[Verdict, list[str], str]:
    """Verdict from geth-replay's ``-drop-tx`` output, given the victim's baseline output."""
    o = out.get("ordering_intervention") or {}
    confounds = o.get("ordering_confounds") or []
    kinds = sorted({k for c in confounds for k in c["kinds"]})
    confounded = [c["index"] for c in confounds]
    tr = _target(out, vi)
    if o.get("fail_closed"):
        v = Verdict(INCONCLUSIVE, "fail_closed", token=token, out_obs=out_obs)
    elif tr is not None and not tr.get("error") and not tr.get("actual_status"):
        v = Verdict(INCONCLUSIVE, "ordering_confound", token=token, out_obs=out_obs, confound_kind="victim_reverted")
    elif not o.get("comparable") or tr is None:
        v = Verdict(INCONCLUSIVE, "incomparable", token=token, out_obs=out_obs)
    else:
        out_cf = net_inflow(_receipt(tr), victim_sender, pools).get(token, 0)
        harm = out_cf - out_obs
        v = Verdict(NO_EFFECT, "", harm, token, out_obs, out_cf, confounded)
        if confounded:
            v.verdict, v.reason, v.confound_kind = INCONCLUSIVE, "ordering_confound", "intermediate_changed"
        elif harm >= max(thr.abs, thr.rel * out_cf):
            v.verdict = CAUSE
    return v, kinds, o.get("incomparable_reason", "")


def layer2_geth(rpc: Rpc, binary: str, bundle_txs: list[tuple[str, str, str]], victim_sender: str, vi: int,
                drop: list[int], pools: set[str], thr: Thresholds, workdir: Path | None = None) -> GethVerdict:
    """Mine the bundle as one block, export it, and decide with geth-replay. The caller owns the
    anvil snapshot around this call (the mined block must be reverted afterwards)."""
    tmp = Path(tempfile.mkdtemp(prefix="mevsim-b2-", dir=workdir))
    try:
        number = rpc.mine_signed(bundle_txs)
        ctx = tmp / "ctx"
        summary = export_context(rpc, number, ctx, vi)
        base = run_geth(binary, ctx, vi, None, tmp / "base.json")
        timing = {"base_wall_ms": round(base.wall_ms, 2)}
        if not base.ok or not base.out.get("acceptance_gate"):
            reason = base.error or ",".join(base.out.get("authenticated_read_failures") or []) or "acceptance_gate=false"
            return GethVerdict(Verdict(INCONCLUSIVE, "replay_gate_failed"), summary, False, timing,
                               incomparable=reason[:200])
        obs = _receipt(_target(base.out, vi))
        inflow = net_inflow(obs, victim_sender, pools)
        gained = [t for t, v in inflow.items() if v > 0]
        if len(gained) != 1:
            return GethVerdict(Verdict(INCONCLUSIVE, "no_victim_output"), summary, True, timing)
        token, out_obs = gained[0], inflow[gained[0]]
        cf = run_geth(binary, ctx, vi, drop, tmp / "drop.json")
        timing["drop_wall_ms"] = round(cf.wall_ms, 2)
        if not cf.ok:
            return GethVerdict(Verdict(INCONCLUSIVE, "engine_error", token=token, out_obs=out_obs), summary, True,
                               timing, incomparable=cf.error[:200])
        timing.update(cf.out.get("timing_ms") or {})
        timing.pop("note", None)
        v, kinds, incomparable = classify_drop_run(cf.out, vi, token, out_obs, victim_sender, pools, thr)
        return GethVerdict(v, summary, True, timing, kinds, incomparable)
    finally:
        if not os.environ.get("MEVSIM_KEEP_CONTEXTS"):
            shutil.rmtree(tmp, ignore_errors=True)
