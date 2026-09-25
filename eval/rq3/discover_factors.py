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

Usage (from the repository root)::

    python -m eval.rq3.discover_factors --exe .cache/framelocal.exe
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from eval.rq3.run_fixed20 import (DEFAULT_CONTEXTS, DEFAULT_MANIFEST, ROOT, build_args, check_context,
                                  sha256_file, sha256_text)

DEFAULT_FACTORS = ROOT / "eval" / "rq3" / "fixed20_factors.json"
RULE = ("read sites (target, selector) called by V inside the harm frame whose value at harm-frame entry "
        "differs from S0, static-evaluable on both; neutral value = S0 value")


def factor_from_discovery(payload: dict[str, Any]) -> dict[str, Any]:
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
    sites = sorted({f"{r['target'].lower()}:{r['selector'].lower()}" for r in reads
                    if r.get("changed_before_entry") and not r.get("is_revert")})
    entry["sites"] = sites
    if not sites:
        entry["reason"] = "no_read_changed_before_entry"
    return entry


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--exe", required=True)
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    ap.add_argument("--contexts", type=Path, default=DEFAULT_CONTEXTS)
    ap.add_argument("--raw-out", type=Path, default=ROOT / ".cache" / "rq3_discover")
    ap.add_argument("--factors", type=Path, default=DEFAULT_FACTORS)
    ap.add_argument("--timeout", type=int, default=900)
    args = ap.parse_args(argv)

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
        cases[name] = factor_from_discovery(json.loads(out.read_text(encoding="utf-8")))

    doc = {"schema": 1, "rule": RULE, "manifest": args.manifest.name,
           "manifest_sha256": sha256_text(args.manifest), "exe_sha256": sha256_file(Path(args.exe)),
           "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "cases": cases}
    args.factors.write_bytes((json.dumps(doc, indent=2, sort_keys=False) + "\n").encode("utf-8"))
    with_factor = sum(1 for c in cases.values() if c["sites"])
    print(f"factors written: {args.factors}  sha256 {sha256_text(args.factors)}")
    print(f"{'case':34} {'frame':>5} {'reads':>6} {'changed':>7} {'sites':>5}  reason")
    for name, c in cases.items():
        print(f"{name.replace('defihacklabs-', '')[:34]:34} {str(c['harm_frame']):>5} {c['n_reads']:>6} "
              f"{c['n_changed_before_entry']:>7} {len(c['sites']):>5}  {c['reason'] or ''}")
    print(f"cases with a factor: {with_factor}/{len(cases)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
