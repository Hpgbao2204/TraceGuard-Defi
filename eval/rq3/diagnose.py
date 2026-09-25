"""RQ3 diagnosis of the v2 CAUSE_BLOCKED cases: is the block a pinning artifact?

For every case with a v2 factor this checks, on the replayed S0 state:

(a) whether each victim address V is an AMM pair: static ``factory()``,
    ``token0()``, ``token1()``, ``getReserves()`` on S0 (``-mode probe``);
(b) whether the pinned reads in the scoped whole-tx run are V's own balance,
    ``balanceOf(x)`` with ``x`` in V, and whether the pinned token is one of
    the pair's tokens;
(c) the function of the reverting frame, decoded from its selector, the
    revert chain, and the revert string,

and reclassifies the guard with the rule of ``eval.rq3.final_table``
(``self_balance_consistency`` first). Nothing here changes a factor or a case.

Usage (from the repository root)::

    python -m eval.rq3.diagnose --exe .cache/framelocal.exe
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from eval.rq3.final_table import DEFAULT_FACTORS, classify_guard, self_balance_reads
from eval.rq3.run_fixed20 import (DEFAULT_CONTEXTS, DEFAULT_MANIFEST, ROOT, build_args, check_context, interpret,
                                  sha256_text)
from eval.rq3.selectors import BALANCE_OF, holder
from eval.rq3.selectors import name as selector_name

PAIR_PROBES = {"factory": "0xc45a0155", "token0": "0x0dfe1681", "token1": "0xd21220a7", "getReserves": "0x0902f1ac"}
TH = {"loss_min_frac": 0.01, "rho": 0.1}


def word_address(out: str | None) -> str | None:
    if not out or len(out) != 66:
        return None
    addr = "0x" + out[-40:].lower()
    return None if int(addr, 16) == 0 else addr


def pair_info(probes: list[dict[str, Any]], victims: list[str]) -> dict[str, Any]:
    """Per victim: the answers to the pair probes and whether it looks like a pair."""
    by = {(p["target"].lower(), p["input"].lower()): p for p in probes}
    info = {}
    for v in victims:
        ans = {}
        for k, sel in PAIR_PROBES.items():
            p = by.get((v.lower(), sel))
            ans[k] = None if (p is None or p.get("error")) else p.get("output")
        f, t0, t1 = (word_address(ans[k]) for k in ("factory", "token0", "token1"))
        reserves_ok = bool(ans["getReserves"]) and len(ans["getReserves"]) == 2 + 96 * 2
        info[v.lower()] = {"is_pair": bool(f and t0 and t1 and reserves_ok), "factory": f, "token0": t0, "token1": t1}
    return info


def diagnose_case(name: str, case: dict[str, Any], factor: dict[str, Any], probe_out: dict[str, Any] | None,
                  scoped: dict[str, Any]) -> dict[str, Any]:
    victims = [v.lower() for v in case["victim"]]
    pairs = pair_info((probe_out or {}).get("probes") or [], victims)
    own = self_balance_reads(scoped, victims)
    pair_tokens = {t for p in pairs.values() for t in (p["token0"], p["token1"]) if t}
    pinned_balance = [p for p in scoped.get("pinned") or [] if (p.get("selector") or "").lower() == BALANCE_OF]
    rv = scoped.get("revert") or {}
    if scoped.get("verdict") == "CAUSE_BLOCKED":
        guard = ({"type": "self_balance_consistency", "basis": f"{len(own)} pinned balanceOf(V)"} if own
                 else classify_guard(rv))
    else:
        guard = None
    return {
        "case": name,
        "victims": victims,
        "factor_sites": factor.get("sites") or [],
        "pairs": pairs,
        "v_is_pair": any(p["is_pair"] for p in pairs.values()),
        "pinned_total": len(scoped.get("pinned") or []),
        "pinned_balanceof": len(pinned_balance),
        "pinned_self_balance": len(own),
        "pinned_holders": sorted({holder(p.get("args")) or "?" for p in pinned_balance}),
        "pinned_token_is_pair_token": any(p["target"].lower() in pair_tokens for p in pinned_balance),
        "scoped_verdict": scoped.get("verdict"),
        "scoped_reason": scoped.get("reason"),
        "revert_origin": rv.get("origin_address"),
        "revert_origin_class": scoped.get("revert_origin"),
        "revert_origin_context_class": rv.get("origin_context_class"),
        "revert_fn": selector_name(rv.get("origin_selector")),
        "revert_kind": rv.get("revert_kind"),
        "revert_message": rv.get("revert_message"),
        "revert_chain": [f"{h.get('address')}.{selector_name(h.get('selector'))}" for h in rv.get("revert_chain") or []],
        "guard": guard,
    }


def run(cmd: list[str], out: Path, timeout: int) -> dict[str, Any] | None:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None
    if proc.returncode != 0:
        out.with_suffix(".stderr.txt").write_text(proc.stderr[-20000:], encoding="utf-8")
        return None
    return json.loads(out.read_text(encoding="utf-8"))


def render(rows: list[dict[str, Any]]) -> str:
    lines = [f"{'case':26} {'V pair':7} {'pins':>4} {'self':>4} {'pair tok':8} {'scoped':14} "
             f"{'revert fn':18} {'message':28} guard"]
    for r in rows:
        g = (r["guard"] or {}).get("type") or "-"
        lines.append(f"{r['case'].replace('defihacklabs-', '')[:26]:26} {str(r['v_is_pair']):7} {r['pinned_total']:>4} "
                     f"{r['pinned_self_balance']:>4} {str(r['pinned_token_is_pair_token']):8} "
                     f"{str(r['scoped_verdict'])[:14]:14} {r['revert_fn'][:18]:18} "
                     f"{str(r['revert_message'] or '')[:28]:28} {g}")
    lines.append("")
    for r in rows:
        if r["revert_chain"]:
            lines.append(f"{r['case'].replace('defihacklabs-', '')[:26]:26} chain: " + " > ".join(
                f"{c.split('.')[0][:8]}.{c.split('.', 1)[1]}" for c in r["revert_chain"]))
        for v, p in r["pairs"].items():
            if p["is_pair"]:
                lines.append(f"{'':26} V {v} pair token0={p['token0']} token1={p['token1']} factory={p['factory']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--exe", required=True)
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    ap.add_argument("--contexts", type=Path, default=DEFAULT_CONTEXTS)
    ap.add_argument("--factors", type=Path, default=DEFAULT_FACTORS)
    ap.add_argument("--out", type=Path, default=ROOT / ".cache" / "rq3_diag")
    ap.add_argument("--timeout", type=int, default=900)
    args = ap.parse_args(argv)

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    fdoc = json.loads(args.factors.read_text(encoding="utf-8"))
    args.out.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, case in sorted(manifest["cases"].items()):
        factor = fdoc["cases"].get(name) or {}
        if not factor.get("sites"):
            continue
        context = args.contexts / name
        if check_context(context, case):
            continue
        print(f"{name}", file=sys.stderr, flush=True)
        probe_path = args.out / f"{name}.probe.json"
        cmd = build_args(args.exe, context, case, "probe", probe_path, TH)
        for v in case["victim"]:
            cmd += [a for sel in PAIR_PROBES.values() for a in ("-probe", f"{v}:{sel}")]
        probe = run(cmd, probe_path, args.timeout)
        scoped_path = args.out / f"{name}.whole-tx.json"
        payload = run(build_args(args.exe, context, case, "whole-tx", scoped_path, TH, factor["sites"]),
                      scoped_path, args.timeout)
        scoped = interpret(payload, "whole-tx", None if payload else "runner_error")
        rows.append(diagnose_case(name, case, factor, probe, scoped))
    doc = {"factors": args.factors.name, "factors_sha256": sha256_text(args.factors), "rows": rows}
    (args.out / "diagnosis.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(render(rows))
    print(f"\nwritten: {args.out / 'diagnosis.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
