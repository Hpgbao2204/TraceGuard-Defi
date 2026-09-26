"""RQ3 final table: one row per case, on the frozen rule-derived factors.

For every case of ``eval/rq3/fixed20_cases.json`` this runs, with the factor
sites frozen in ``eval/rq3/fixed20_factors.json`` (never re-discovered):

* ``unscoped``     whole-tx, the factor pinned for every caller (attacker and
                   third parties included); the scoping ablation
* ``whole-tx``     whole-tx, the factor pinned only where V reads it (main axis)
* ``frame-local``  the same intervention, only inside the harm frame (secondary)
* ``isolation``    identity stubs at the same read sites
* dose-response    scoped whole-tx and frame-local at lambda < 1

and then classifies each CAUSE_BLOCKED revert by the guard that fired.

Guard types (rule, applied to the revert of the origin frame, in this order):

* ``self_balance_consistency``  the intervention pinned ``balanceOf(x)`` read by
                   V with ``x`` in V: the victim's own balance was set back to
                   S0, so any check that compares balance with internal
                   accounting (an AMM pair's input amount, ``K``) fails by
                   construction. Not causal evidence.

* ``security``     health / collateral / solvency / liquidation / debt / access
                   checks, matched on the revert string
* ``consistency``  accounting checks: the constant-product ``K`` check, reserve
                   or balance mismatch, insufficient balance or allowance,
                   arithmetic panic (overflow, division by zero, assert)
* ``other``        a revert string that matches neither list (slippage, deadline, ...)
* ``unknown``      no revert string (empty revert, custom error, halt)

Only CAUSE and CAUSE_BLOCKED(security) count as strong causal evidence.
The totals also give the "naive vs gated" ladder: how many cases a naive
reading of the rule-derived intervention would claim (the counterfactual
reverted or lost less), how many survive the gates, and how many are strong.
CAUSE_BLOCKED with any other guard type is reported as
CAUSE_BLOCKED(<type>) and counted separately. A manual override file
(``--guard-overrides``) may classify an ``unknown`` or ``other`` revert after
reading the contract source; every override is marked ``manual`` in the table
and listed in the JSON, so it can be disclosed as post hoc.

Usage (from the repository root)::

    python -m eval.rq3.final_table --exe .cache/framelocal.exe
    python -m eval.rq3.final_table --reuse            # rebuild from .cache/rq3_final/runs.json
    python -m eval.rq3.final_table --reuse --json-only
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

import subprocess

from eval.rq3.selectors import BALANCE_OF, holder
from eval.rq3.selectors import name as selector_name
from eval.rq3.run_fixed20 import (DEFAULT_CONTEXTS, DEFAULT_MANIFEST, ROOT, dose_modes, run_case, sha256_file,
                                  sha256_text, summarize, wilson)

DEFAULT_FACTORS = ROOT / "eval" / "rq3" / "fixed20_factors.json"
DEFAULT_OVERRIDES = ROOT / "eval" / "rq3" / "guard_overrides.json"
DEFAULT_OUT = ROOT / ".cache" / "rq3_final"
# Factors frozen at commit 970ce98 (v2, proof-bound state). A different file is refused.
FROZEN_FACTORS_SHA256 = "ec137bd655f450a76bdf6d763b48a388da8660ab1f7b2b7d8283ba9cc18c36b4"
RUN_MODES = ("unscoped", "whole-tx", "frame-local", "isolation")
DEFAULT_DOSE = (0.25, 0.5, 0.75)
BLOCKED = ("CAUSE", "CAUSE_BLOCKED")


SECURITY_PATTERNS = [
    r"health", r"collateral", r"solven", r"liquidat", r"\bltv\b", r"loan.to.value", r"\bdebt\b",
    r"borrow", r"margin", r"under.?water", r"unauthori[sz]ed", r"not.authori[sz]ed", r"only.?owner",
    r"caller is not", r"access", r"forbidden", r"permission", r"not.allowed",
]
CONSISTENCY_PATTERNS = [
    r"(^|[^a-z])k$", r": k\b", r"\binvariant\b", r"reserve", r"insufficient.?liquidity", r"exceeds.balance",
    r"insufficient.?balance", r"allowance", r"overflow", r"underflow", r"subtraction", r"division",
    r"insufficient.?input", r"transfer.?failed", r"^t?f$", r"^stf$", r"balance",
]
CONSISTENCY_PANICS = ("0x01", "0x11", "0x12", "0x32")


def classify_guard(revert: dict[str, Any] | None) -> dict[str, Any]:
    """Guard type of a revert by the fixed rule in the module docstring."""
    if not revert:
        return {"type": "unknown", "basis": "no_revert_detail"}
    kind = revert.get("revert_kind") or ""
    msg = (revert.get("revert_message") or "").strip()
    if kind == "panic":
        code = msg.split(" ", 1)[0]
        if code in CONSISTENCY_PANICS:
            return {"type": "consistency", "basis": f"panic {msg}"}
        return {"type": "other", "basis": f"panic {msg}"}
    if kind != "error_string" or not msg:
        return {"type": "unknown", "basis": f"{kind or 'no_kind'} {msg}".strip()}
    low = msg.lower()
    for pat in SECURITY_PATTERNS:
        if re.search(pat, low):
            return {"type": "security", "basis": f"string matches /{pat}/"}
    for pat in CONSISTENCY_PATTERNS:
        if re.search(pat, low):
            return {"type": "consistency", "basis": f"string matches /{pat}/"}
    return {"type": "other", "basis": "string matches no list"}


def factor_label(sites: list[str]) -> str:
    if not sites:
        return "-"
    parts = []
    for s in sites:
        target, _, sel = s.partition(":")
        sel, _, args = sel.partition(":")
        who = f"({holder(args)[:8]}..)" if args and holder(args) else ""
        parts.append(f"{target[:6]}..{target[-4:]}.{selector_name(sel)}{who}")
    return f"{len(sites)}: " + ", ".join(parts)


def verdict_cell(rec: dict[str, Any] | None) -> str:
    if not rec:
        return "-"
    v = rec.get("verdict", "?")
    if v == "INCONCLUSIVE":
        return f"INC({(rec.get('reason') or '?').split(':')[0]})"
    return v


def smallest_blocked_lambda(recs: dict[str, dict[str, Any]], mode: str, lambdas: list[float]) -> float | None:
    """Smallest lambda from which every larger dose on the grid (and lambda 1)
    still blocks: CAUSE or CAUSE_BLOCKED."""
    if recs.get(mode, {}).get("verdict") not in BLOCKED:
        return None
    best = 1.0
    for lam in sorted(lambdas, reverse=True):
        if recs.get(f"{mode}@{lam:g}", {}).get("verdict") in BLOCKED:
            best = lam
        else:
            break
    return best


def self_balance_reads(rec: dict[str, Any], victims: list[str] | tuple[str, ...]) -> list[dict[str, Any]]:
    """Pinned balanceOf(x) reads made by V with x in V (the victim's own balance)."""
    vset = {v.lower() for v in victims}
    return [p for p in rec.get("pinned") or []
            if (p.get("selector") or "").lower() == BALANCE_OF and p.get("kind") != "code_override"
            and (p.get("caller_class") == "victim" or (p.get("caller") or "").lower() in vset)
            and holder(p.get("args")) in vset]


def final_row(name: str, factor: dict[str, Any], recs: dict[str, dict[str, Any]], lambdas: list[float],
              overrides: dict[str, Any], victims: list[str] | tuple[str, ...] = ()) -> dict[str, Any]:
    sites = factor.get("sites") or []
    un, sc, fl, iso = (recs.get(m, {}) for m in RUN_MODES)
    row: dict[str, Any] = {
        "case": name,
        "factor": factor_label(sites),
        "factor_sites": sites,
        "factor_rule_reason": factor.get("reason"),
        "unscoped": {"verdict": un.get("verdict"), "reason": un.get("reason"), "origin": un.get("revert_origin"),
                     "reads_by_caller": un.get("reads_by_caller")},
        "scoped_whole_tx": {"verdict": sc.get("verdict"), "reason": sc.get("reason"), "origin": sc.get("revert_origin"),
                            "reads_by_caller": sc.get("reads_by_caller")},
        "frame_local": {"verdict": fl.get("verdict"), "reason": fl.get("reason"), "origin": fl.get("revert_origin")},
        "isolation": iso.get("verdict"),
        "dose_min_blocked_lambda": {"whole_tx": smallest_blocked_lambda(recs, "whole-tx", lambdas),
                                    "frame_local": smallest_blocked_lambda(recs, "frame-local", lambdas)},
        "revert": sc.get("revert"),
        "self_balance_pins": len(self_balance_reads(sc, victims)),
        "guard": None,
    }
    if not sites:
        row["final"] = f"INCONCLUSIVE(no_declared_factor:{factor.get('reason') or 'empty'})"
        row["final_reason"] = f"no_declared_factor:{factor.get('reason') or 'empty'}"
        return row
    v = sc.get("verdict")
    if v == "INCONCLUSIVE":
        reason = sc.get("reason") or "unknown"
        row["final"], row["final_reason"] = f"INCONCLUSIVE({reason})", reason
        return row
    if iso.get("verdict") == "FAIL":
        row["final"], row["final_reason"] = "INCONCLUSIVE(isolation_failed)", "isolation_failed"
        return row
    if v == "CAUSE_BLOCKED":
        own = self_balance_reads(sc, victims)
        if own:
            guard = {"type": "self_balance_consistency",
                     "basis": f"{len(own)} pinned balanceOf(V) read(s), e.g. {own[0]['target']}.balanceOf({holder(own[0]['args'])})"}
        else:
            guard = classify_guard(sc.get("revert"))
        guard["source"] = "rule"
        ov = overrides.get(name)
        if ov and guard["type"] in ("unknown", "other"):
            guard = {"type": ov["type"], "basis": ov.get("note", ""), "source": "manual"}
        row["guard"] = guard
        row["final"] = f"CAUSE_BLOCKED({guard['type']})"
    else:
        row["final"] = v
    row["final_reason"] = None
    row["frame_local_agrees"] = fl.get("verdict") == v
    return row


def totals(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    valid = [r for r in rows if not r["final"].startswith("INCONCLUSIVE")]
    strong = [r for r in valid if r["final"] in ("CAUSE", "CAUSE_BLOCKED(security)")]
    with_factor = [r for r in rows if r["factor_sites"]]
    inc = Counter(r["final_reason"] for r in rows if r["final_reason"])
    un_orig = Counter(r["unscoped"]["origin"] or "no_revert" for r in with_factor)
    sc_orig = Counter(r["scoped_whole_tx"]["origin"] or "no_revert" for r in with_factor)
    un_reads = Counter()
    for r in with_factor:
        un_reads.update(r["unscoped"].get("reads_by_caller") or {})
    def changed(r: dict[str, Any]) -> bool:
        sc = r["scoped_whole_tx"]
        return bool(sc.get("origin")) or sc.get("verdict") in ("CAUSE", "CAUSE_BLOCKED", "PARTIAL")
    naive = [r for r in with_factor if changed(r)]
    naive_blocked = [r for r in with_factor if r["scoped_whole_tx"].get("verdict") == "CAUSE_BLOCKED"
                     or r["scoped_whole_tx"].get("verdict") == "CAUSE"]
    return {
        "n_cases": n,
        "naive_vs_gated": {
            "naive_any_change": len(naive),
            "naive_any_change_wilson95": wilson(len(naive), n),
            "runner_cause_or_blocked": len(naive_blocked),
            "runner_cause_or_blocked_wilson95": wilson(len(naive_blocked), n),
            "gated_valid": len(valid),
            "strong_evidence": len(strong),
            "strong_evidence_wilson95": wilson(len(strong), n),
            "guard_types": dict(sorted(Counter((r.get("guard") or {}).get("type") for r in rows
                                               if r.get("guard")).items())),
        },
        "with_factor": len(with_factor),
        "with_factor_wilson95": wilson(len(with_factor), n),
        "coverage_valid": len(valid),
        "coverage_wilson95": wilson(len(valid), n),
        "strong_evidence": len(strong),
        "strong_evidence_wilson95": wilson(len(strong), n),
        "final": dict(sorted(Counter(r["final"].split("(")[0] if r["final"].startswith("INCONCLUSIVE")
                                     else r["final"] for r in rows).items())),
        "inconclusive_reasons": dict(sorted(inc.items())),
        "revert_origin_with_factor": {"unscoped": dict(sorted(un_orig.items())),
                                      "scoped_whole_tx": dict(sorted(sc_orig.items()))},
        "unscoped_pinned_reads_by_caller": dict(sorted(un_reads.items())),
        "isolation": dict(sorted(Counter(r["isolation"] or "-" for r in with_factor).items())),
        "frame_local_agrees": sum(1 for r in valid if r.get("frame_local_agrees")),
        "manual_guard_overrides": sorted(r["case"] for r in rows if (r.get("guard") or {}).get("source") == "manual"),
    }


def render(doc: dict[str, Any]) -> str:
    cols = ["case", "factor", "unscoped", "scoped whole-tx", "frame-local", "iso", "dose", "guard", "final"]
    widths = [26, 30, 28, 24, 24, 5, 9, 13, 36]
    lines = ["  ".join(f"{c:{w}}" for c, w in zip(cols, widths))]
    lines.append("-" * len(lines[0]))
    for r in doc["rows"]:
        un = verdict_cell(r["unscoped"]) + (f"/{r['unscoped']['origin']}" if r["unscoped"].get("origin") else "")
        sc = verdict_cell(r["scoped_whole_tx"]) + (f"/{r['scoped_whole_tx']['origin']}" if r["scoped_whole_tx"].get("origin") else "")
        d = r["dose_min_blocked_lambda"]["whole_tx"]
        g = r["guard"]
        guard = "-" if not g else {"self_balance_consistency": "self_balance"}.get(g["type"], g["type"]) + \
            ("*" if g.get("source") == "manual" else "")
        cells = [r["case"].replace("defihacklabs-", ""), r["factor"], un, sc, verdict_cell(r["frame_local"]),
                 (r["isolation"] or "-")[:5], "-" if d is None else f"{d:g}", guard, r["final"]]
        lines.append("  ".join(f"{str(c)[:w]:{w}}" for c, w in zip(cells, widths)))
    t = doc["totals"]
    lines += [
        "",
        f"factor present      {t['with_factor']}/{t['n_cases']}  CI95={t['with_factor_wilson95']}",
        f"coverage (valid)    {t['coverage_valid']}/{t['n_cases']}  CI95={t['coverage_wilson95']}",
        f"strong evidence     {t['strong_evidence']}/{t['n_cases']}  CI95={t['strong_evidence_wilson95']}"
        "  (CAUSE or CAUSE_BLOCKED(security))",
        f"final               {t['final']}",
        f"naive vs gated      any change {t['naive_vs_gated']['naive_any_change']}/{t['n_cases']}"
        f" -> runner CAUSE/CAUSE_BLOCKED {t['naive_vs_gated']['runner_cause_or_blocked']}/{t['n_cases']}"
        f" -> gated valid {t['naive_vs_gated']['gated_valid']}/{t['n_cases']}"
        f" -> strong {t['naive_vs_gated']['strong_evidence']}/{t['n_cases']}   guard types {t['naive_vs_gated']['guard_types']}",
        f"inconclusive        {t['inconclusive_reasons']}",
        f"revert origin (cases with a factor)  unscoped={t['revert_origin_with_factor']['unscoped']}"
        f"  scoped={t['revert_origin_with_factor']['scoped_whole_tx']}",
        f"unscoped pinned reads by caller      {t['unscoped_pinned_reads_by_caller']}",
        f"isolation {t['isolation']}   frame-local agrees with scoped whole-tx on {t['frame_local_agrees']}/{t['coverage_valid']} valid",
    ]
    if t["manual_guard_overrides"]:
        lines.append(f"guard marked * = manual override (post hoc): {t['manual_guard_overrides']}")
    lines.append("")
    lines.append("revert detail (scoped whole-tx):")
    for r in doc["rows"]:
        rv = r.get("revert")
        if not rv:
            continue
        g = r.get("guard") or {}
        lines.append(f"  {r['case'].replace('defihacklabs-', '')[:26]:26} origin={rv.get('origin_address')} "
                     f"fn={selector_name(rv.get('origin_selector'))} "
                     f"{rv.get('revert_kind')}={rv.get('revert_message')!r} guard={g.get('type')} ({g.get('basis')})")
        chain = " > ".join(f"{h.get('address', '')[:8]}.{selector_name(h.get('selector'))}" for h in rv.get("revert_chain") or [])
        if chain:
            lines.append(f"  {'':26} chain: {chain}")
    return "\n".join(lines)


def check_frozen(path: Path, sha: str, fdoc: dict[str, Any]) -> str | None:
    """Factors must be declared before the run: v2 is the file frozen at 970ce98;
    any later rule version must be committed and unmodified in git, and the
    commit that holds it is recorded."""
    if sha == FROZEN_FACTORS_SHA256:
        return "970ce98"
    if fdoc.get("rule_version") in (None, "v2") and fdoc.get("manifest") in (None, "fixed20_cases.json"):
        # v2 on the frozen manifest is exactly the file frozen at 970ce98; v2 re-derived on another
        # manifest (the published boundary amendment) must be committed and clean, like any later rule.
        raise SystemExit(f"factors file {path} is not the frozen v2 (sha256 {sha})")
    try:
        tracked = subprocess.run(["git", "ls-files", "--error-unmatch", str(path)], capture_output=True, cwd=ROOT)
        dirty = subprocess.run(["git", "status", "--porcelain", "--", str(path)], capture_output=True, text=True, cwd=ROOT)
        commit = subprocess.run(["git", "log", "-1", "--format=%h", "--", str(path)], capture_output=True, text=True,
                                cwd=ROOT)
    except OSError as exc:
        raise SystemExit(f"cannot check that {path} is committed: {exc}")
    if tracked.returncode != 0 or dirty.stdout.strip() or not commit.stdout.strip():
        raise SystemExit(f"commit {path} before running on it (factors are declared before any intervention)")
    return commit.stdout.strip()


def render_compare(a: dict[str, Any], b: dict[str, Any]) -> str:
    """Two summaries (e.g. factors v2 and v3) side by side, one line per case."""
    va, vb = a.get("factors_rule_version", "A"), b.get("factors_rule_version", "B")
    ra = {r["case"]: r for r in a["rows"]}
    lines = [f"{'case':26}  {'factor ' + va:32}  {'final ' + va:36}  {'factor ' + vb:32}  {'final ' + vb:36}"]
    for r in b["rows"]:
        o = ra.get(r["case"], {"factor": "-", "final": "-"})
        lines.append(f"{r['case'].replace('defihacklabs-', '')[:26]:26}  {o['factor'][:32]:32}  {o['final'][:36]:36}  "
                     f"{r['factor'][:32]:32}  {r['final'][:36]:36}")
    for label, d in ((va, a), (vb, b)):
        t = d["totals"]
        nv = t.get("naive_vs_gated", {})
        lines.append(f"{label}: factor {t['with_factor']}/{t['n_cases']}, valid {t['coverage_valid']}/{t['n_cases']} "
                     f"CI95={t['coverage_wilson95']}, strong {t['strong_evidence']}/{t['n_cases']}, "
                     f"guard types {nv.get('guard_types')}")
    return "\n".join(lines)


def load_overrides(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {}
    doc = json.loads(path.read_text(encoding="utf-8"))
    out = doc.get("cases", {})
    for name, ov in out.items():
        if ov.get("type") not in ("security", "consistency", "other") or not ov.get("note"):
            raise SystemExit(f"guard override for {name} needs type security|consistency|other and a note")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--exe", help="built cmd/framelocal binary (not needed with --reuse)")
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    ap.add_argument("--contexts", type=Path, default=DEFAULT_CONTEXTS)
    ap.add_argument("--factors", type=Path, default=DEFAULT_FACTORS)
    ap.add_argument("--guard-overrides", type=Path, default=DEFAULT_OVERRIDES)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--only", action="append", default=[])
    ap.add_argument("--dose", default=",".join(f"{x:g}" for x in DEFAULT_DOSE))
    ap.add_argument("--loss-min-frac", type=float, default=0.01)
    ap.add_argument("--rho", type=float, default=0.1)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--reuse", action="store_true", help="rebuild the table from <out>/runs.json without running")
    ap.add_argument("--json-only", action="store_true", help="print summary.json to stdout instead of the table")
    ap.add_argument("--compare", type=Path, default=None,
                    help="another summary.json (e.g. the v2 table) to print side by side with this one")
    args = ap.parse_args(argv)

    factors_sha = sha256_text(args.factors)
    fdoc = json.loads(args.factors.read_text(encoding="utf-8"))
    factors_commit = check_frozen(args.factors, factors_sha, fdoc)
    manifest_sha = sha256_text(args.manifest)
    if fdoc.get("manifest_sha256") != manifest_sha:
        raise SystemExit("factors were derived from a different manifest")
    lambdas = [float(x) for x in args.dose.split(",") if x.strip()]
    if any(not 0 < lam < 1 for lam in lambdas):
        raise SystemExit("--dose lambdas must be in (0, 1)")
    args.out.mkdir(parents=True, exist_ok=True)
    runs_path = args.out / "runs.json"
    mode_list = RUN_MODES + dose_modes(lambdas)

    if args.reuse:
        runs = json.loads(runs_path.read_text(encoding="utf-8"))
        per_case, lock = runs["cases"], runs["lock"]
        if lock.get("factors_sha256") not in (None, factors_sha):
            raise SystemExit(f"{runs_path} was run with other factors (sha256 {lock.get('factors_sha256')})")
        lambdas = lock["dose_lambdas"]
    else:
        if not args.exe:
            ap.error("--exe is required unless --reuse")
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        cases = manifest["cases"]
        if args.only:
            cases = {k: v for k, v in cases.items() if k in set(args.only)}
        thresholds = {"loss_min_frac": args.loss_min_frac, "rho": args.rho}
        lock = {"manifest": args.manifest.name, "manifest_sha256": manifest_sha, "n_cases": len(cases),
                "exe_sha256": sha256_file(Path(args.exe)), "thresholds": thresholds,
                "factors": args.factors.name, "factors_sha256": factors_sha, "factors_commit": factors_commit,
                "factors_rule_version": fdoc.get("rule_version", "v2"), "dose_lambdas": lambdas,
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        per_case = {}
        for i, (name, case) in enumerate(sorted(cases.items()), 1):
            print(f"[{i}/{len(cases)}] {name}", file=sys.stderr, flush=True)
            factor = fdoc["cases"].get(name, {"sites": [], "reason": "missing_from_factors"})
            per_case[name] = run_case(args.exe, args.contexts, args.out / "raw", name, case, thresholds,
                                      args.timeout, factor, mode_list)
        runs_path.write_text(json.dumps({"lock": lock, "cases": per_case}, indent=2) + "\n", encoding="utf-8")

    overrides = load_overrides(args.guard_overrides)
    victims = {k: v.get("victim", []) for k, v in json.loads(args.manifest.read_text(encoding="utf-8"))["cases"].items()}
    rows = [final_row(name, fdoc["cases"].get(name, {"sites": [], "reason": "missing_from_factors"}), recs,
                      lambdas, overrides, victims.get(name, [])) for name, recs in sorted(per_case.items())]
    doc = {"schema": 1, **lock,
           "guard_overrides_sha256": sha256_text(args.guard_overrides) if args.guard_overrides.is_file() else None,
           "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "rows": rows, "totals": totals(rows), "modes": summarize(per_case, mode_list)["modes"]}
    (args.out / "summary.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    if args.json_only:
        print(json.dumps(doc, indent=2))
    else:
        print(f"factors sha256 {factors_sha}  manifest sha256 {manifest_sha}")
        print(render(doc))
        if args.compare is not None:
            print("")
            print(render_compare(json.loads(args.compare.read_text(encoding="utf-8")), doc))
        print(f"\nwritten: {args.out / 'summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
