"""RQ3 step 1: derive each case's factor by a fixed rule, before any intervention.

Rule (applied identically to all 20 cases, no manual edits):

    The factor of a case is the set of read sites (target, selector) that the
    victim V calls inside the harm frame, whose return value at harm-frame
    entry already differs from its value on S0 (the pre-transaction state),
    and which are static-evaluable on both states. These are exactly the reads
    the attacker changed before V was entered. The neutral value is the S0
    value. Reads changed only inside the frame (by V itself) do not qualify.

A case with no harm frame, a failed replay gate, or no qualifying read has an
empty factor and is reported as such by the runner, never dropped.

Commit the written ``eval/rq3/fixed20_factors.json`` (its SHA-256 is printed)
before running ``eval.rq3.run_fixed20 --factors``, so the factor choice is
fixed before any counterfactual result is seen.

Rule v3 (``--rule v3``, declared after v2 results showed that pinning a
victim's own token balance makes an AMM pair revert on its own consistency
check): the v2 rule, minus

* ``balanceOf(x)`` reads with ``x`` one of the case's victim addresses V
  (the victim's own balance is state, not an input the attacker set);
* selectors with no economic value: ``approve``, ``allowance``,
  ``supportsInterface``.

A v3 ``balanceOf`` site names its holder (``target:selector:args``) so the
excluded self-balance reads at the same token are not pinned. Everything else
is unchanged. v3 must be a subset of v2 at (target, selector); any difference
is printed and recorded. v3 is written to ``fixed20_factors_v3.json``.

Usage (from the repository root)::

    python -m eval.rq3.discover_factors --exe .cache/framelocal.exe
    python -m eval.rq3.discover_factors --exe .cache/framelocal.exe --rule v3
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from eval.rq3.selectors import BALANCE_OF, NON_ECONOMIC, holder
from eval.rq3.run_fixed20 import (DEFAULT_CONTEXTS, DEFAULT_MANIFEST, ROOT, build_args, check_context,
                                  sha256_file, sha256_text)

DEFAULT_FACTORS = ROOT / "eval" / "rq3" / "fixed20_factors.json"
DEFAULT_FACTORS_V3 = ROOT / "eval" / "rq3" / "fixed20_factors_v3.json"
RULE = ("read sites (target, selector) called by V inside the harm frame whose value at harm-frame entry "
        "differs from S0, static-evaluable on both; neutral value = S0 value")
RULE_V3 = (RULE + "; excluding balanceOf(x) with x in V (self balance) and the non-economic selectors "
           "approve, allowance, supportsInterface; balanceOf sites name their holder (target:selector:args)")


def _v3_keep(read: dict[str, Any], victims: set[str]) -> tuple[bool, str | None]:
    sel = (read.get("selector") or "").lower()
    if sel in NON_ECONOMIC:
        return False, f"non_economic:{NON_ECONOMIC[sel]}"
    if sel == BALANCE_OF and holder(read.get("args")) in victims:
        return False, "self_balance"
    return True, None


def _site(read: dict[str, Any], rule: str) -> str:
    base = f"{read['target'].lower()}:{read['selector'].lower()}"
    if rule == "v3" and read["selector"].lower() == BALANCE_OF:
        if not read.get("args"):
            raise ValueError("v3 needs read args; rebuild framelocal from this branch")
        return f"{base}:{read['args'].lower()}"
    return base


def factor_from_discovery(payload: dict[str, Any], rule: str = "v2",
                          victims: list[str] | None = None) -> dict[str, Any]:
    """Apply the rule to one discover-mode output."""
    res = payload.get("frame_local_result") or {}
    reads = payload.get("scoped_reads") or []
    entry: dict[str, Any] = {
        "harm_frame": res.get("target_frame_index"),
        "n_reads": len(reads),
        "n_changed_before_entry": sum(1 for r in reads if r.get("changed_before_entry")),
        "sites": [],
        "reason": None,
    }
    if not payload.get("replay_gate"):
        entry["reason"] = "replay_gate_failed"
        return entry
    if res.get("reason_code") == "no_harm_frame" or res.get("target_frame_index", -1) < 0:
        entry["reason"] = "no_harm_frame"
        return entry
    qualifying = [r for r in reads if r.get("changed_before_entry") and not r.get("is_revert")]
    if rule == "v3":
        vset = {v.lower() for v in victims or []}
        kept, dropped = [], {}
        for r in qualifying:
            keep, why = _v3_keep(r, vset)
            if keep:
                kept.append(r)
            else:
                dropped[why] = dropped.get(why, 0) + 1
        entry["excluded"] = dict(sorted(dropped.items()))
        if qualifying and not kept:
            entry["sites"] = []
            entry["reason"] = "only_self_balance_or_non_economic"
            return entry
        qualifying = kept
    sites = sorted({_site(r, rule) for r in qualifying})
    entry["sites"] = sites
    if not sites:
        entry["reason"] = "no_read_changed_before_entry"
    return entry


def subset_check(v3_cases: dict[str, Any], v2_cases: dict[str, Any]) -> dict[str, list[str]]:
    """v3 sites not present in v2 at (target, selector), per case; must be empty."""
    extra = {}
    for name, c in v3_cases.items():
        v2 = set(v2_cases.get(name, {}).get("sites") or [])
        bad = [s for s in c.get("sites") or [] if ":".join(s.split(":")[:2]) not in v2]
        if bad:
            extra[name] = bad
    return extra


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--exe", required=True)
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    ap.add_argument("--contexts", type=Path, default=DEFAULT_CONTEXTS)
    ap.add_argument("--raw-out", type=Path, default=None, help="default .cache/rq3_discover (v2) or .cache/rq3_discover_v3")
    ap.add_argument("--factors", type=Path, default=None,
                    help="output file (default fixed20_factors.json, or fixed20_factors_v3.json with --rule v3)")
    ap.add_argument("--rule", choices=("v2", "v3"), default="v2")
    ap.add_argument("--v2", type=Path, default=DEFAULT_FACTORS, help="frozen v2 factors, for the v3 subset check")
    ap.add_argument("--timeout", type=int, default=900)
    args = ap.parse_args(argv)

    if args.raw_out is None:
        args.raw_out = ROOT / ".cache" / ("rq3_discover_v3" if args.rule == "v3" else "rq3_discover")
    if args.factors is None:
        args.factors = DEFAULT_FACTORS_V3 if args.rule == "v3" else DEFAULT_FACTORS
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    th = {"loss_min_frac": 0.01, "rho": 0.1}  # unused by discover; required by the CLI
    args.raw_out.mkdir(parents=True, exist_ok=True)
    cases: dict[str, Any] = {}
    for i, (name, case) in enumerate(sorted(manifest["cases"].items()), 1):
        print(f"[{i}/{len(manifest['cases'])}] {name}", file=sys.stderr, flush=True)
        context = args.contexts / name
        bad = check_context(context, case)
        if bad:
            cases[name] = {"harm_frame": None, "n_reads": 0, "n_changed_before_entry": 0, "sites": [], "reason": bad}
            continue
        out = args.raw_out / f"{name}.json"
        cmd = build_args(args.exe, context, case, "discover", out, th)
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=args.timeout)
            err = None if proc.returncode == 0 else f"exit_{proc.returncode}"
        except subprocess.TimeoutExpired:
            err = "timeout"
        if err:
            cases[name] = {"harm_frame": None, "n_reads": 0, "n_changed_before_entry": 0, "sites": [], "reason": err}
            continue
        cases[name] = factor_from_discovery(json.loads(out.read_text(encoding="utf-8")), args.rule, case["victim"])

    doc = {"schema": 1, "rule_version": args.rule, "rule": RULE_V3 if args.rule == "v3" else RULE,
           "manifest": args.manifest.name,
           "manifest_sha256": sha256_text(args.manifest), "exe_sha256": sha256_file(Path(args.exe)),
           "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "cases": cases}
    if args.rule == "v3":
        v2doc = json.loads(args.v2.read_text(encoding="utf-8"))
        doc["v2_factors_sha256"] = sha256_text(args.v2)
        doc["not_subset_of_v2"] = subset_check(cases, v2doc["cases"])
    args.factors.write_bytes((json.dumps(doc, indent=2, sort_keys=False) + "\n").encode("utf-8"))
    with_factor = sum(1 for c in cases.values() if c["sites"])
    print(f"factors written: {args.factors}  sha256 {sha256_text(args.factors)}")
    print(f"{'case':34} {'frame':>5} {'reads':>6} {'changed':>7} {'sites':>5}  reason")
    for name, c in cases.items():
        print(f"{name.replace('defihacklabs-', '')[:34]:34} {str(c['harm_frame']):>5} {c['n_reads']:>6} "
              f"{c['n_changed_before_entry']:>7} {len(c['sites']):>5}  {c['reason'] or ''}")
    print(f"cases with a factor: {with_factor}/{len(cases)}")
    if args.rule == "v3":
        for name, c in cases.items():
            if c.get("excluded"):
                print(f"  {name.replace('defihacklabs-', '')[:34]:34} excluded {c['excluded']}")
        if doc["not_subset_of_v2"]:
            print(f"WARNING v3 sites not in v2: {doc['not_subset_of_v2']}")
        else:
            print("v3 is a subset of v2 at (target, selector)")
        print("Commit this file BEFORE running eval.rq3.final_table --factors on it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
