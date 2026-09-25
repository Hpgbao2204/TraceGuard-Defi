"""RQ3: run the fixed-20 queue through the frame-local runner.

For every case in ``eval/rq3/fixed20_cases.json`` (victim/attacker frozen
before any intervention) this runs four modes of
``tools/geth-replay/cmd/framelocal``:

* ``whole-tx``    read-site-scoped intervention over the whole transaction
* ``frame-local`` the same intervention, only inside the victim harm frame
* ``isolation``   identity stubs at the same read sites (must reproduce baseline)
* ``sham``        a different value at an unrelated read (loss must not change)

Verdicts are admitted only when the replay gate holds (authenticated prestate,
exact prefix, exact baseline target); otherwise the case is
``INCONCLUSIVE(replay_gate_failed)``. The SHA-256 of the input manifest is
written to the output directory before the first run.

Usage (from the repository root)::

    python -m eval.rq3.run_fixed20 --exe .cache/framelocal.exe
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = ROOT / "eval" / "rq3" / "fixed20_cases.json"
DEFAULT_CONTEXTS = ROOT / "eval" / "results" / "m4" / "b2-contexts-fresh"
DEFAULT_OUT = ROOT / ".cache" / "rq3"
MODES = ("whole-tx", "frame-local", "isolation", "sham")
# Dose-response modes are written "whole-tx@0.5" / "frame-local@0.5": the
# factor is moved only a fraction lambda of the way from observed to S0.


def base_mode(mode: str) -> str:
    return mode.split("@", 1)[0]


def dose_modes(lambdas: list[float]) -> tuple[str, ...]:
    return tuple(f"{m}@{lam:g}" for lam in lambdas for m in ("whole-tx", "frame-local"))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_text(path: Path) -> str:
    """SHA-256 of a text file with CRLF normalised to LF, so the hash of a
    committed JSON file is the same on Windows and Linux checkouts."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def wilson(k: int, n: int, z: float = 1.96) -> list[float] | None:
    """Wilson score interval for k successes out of n (95% by default)."""
    if n <= 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return [round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)]


def check_context(context: Path, case: dict[str, Any]) -> str | None:
    """Return a reason string if the context does not hold the frozen target."""
    if not context.is_dir():
        return "missing_context"
    try:
        txs = json.loads((context / "transactions.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "unreadable_transactions"
    idx = int(case["tx_index"])
    if len(txs) != idx + 1:
        return f"context_has_{len(txs)}_txs_expected_{idx + 1}"
    if str(txs[idx].get("hash", "")).lower() != str(case["tx_hash"]).lower():
        return "target_hash_mismatch"
    return None


def build_args(exe: str, context: Path, case: dict[str, Any], mode: str, out: Path,
               thresholds: dict[str, float], sites: list[str] | None = None) -> list[str]:
    args = [exe, "-context", str(context), "-output", str(out), "-lean",
            "-target-index", str(case["tx_index"]),
            "-loss-min-frac", str(thresholds["loss_min_frac"]), "-rho", str(thresholds["rho"])]
    proofs = context / "prestate_proofs.json"
    if proofs.is_file():
        args += ["-proofs", str(proofs)]
    for v in case["victim"]:
        args += ["-victim", v]
    for a in case["attacker"]:
        args += ["-attacker", a]
    for site in sites or []:
        args += ["-read-site", site]
    base, _, lam = mode.partition("@")
    if base == "whole-tx":
        args += ["-mode", "whole-tx", "-scoped-price"]
    else:
        args += ["-mode", base]
    if lam:
        args += ["-dose-lambda", lam]
    return args


def interpret(payload: dict[str, Any] | None, mode: str, error: str | None = None) -> dict[str, Any]:
    """Reduce one runner output to the fields the summary needs."""
    if payload is None:
        return {"verdict": "INCONCLUSIVE", "reason": error or "runner_error"}
    key = "whole_tx_result" if base_mode(mode) == "whole-tx" else "frame_local_result"
    res = payload.get(key) or {}
    rec: dict[str, Any] = {
        "verdict": res.get("verdict", "INCONCLUSIVE"),
        "reason": res.get("reason_code") or None,
        "replay_gate": bool(payload.get("replay_gate")),
        "target_frame_index": res.get("target_frame_index"),
        "intervention_sites": res.get("intervention_sites", 0),
        "token_losses": res.get("token_losses") or [],
        "attacker_input_match": (res.get("attacker_input") or {}).get("match"),
        "gas_delta": res.get("gas_delta"),
    }
    if not res:
        rec["reason"] = "no_verdict_in_output"
    ro = res.get("revert_origin") or payload.get("revert_origin") or {}
    if res.get("reverted") and ro.get("has_revert"):
        rec["revert_origin"] = ro.get("origin_class") or "unknown"
    if not rec["replay_gate"]:
        rec["raw_verdict"] = rec["verdict"]
        rec["verdict"] = "INCONCLUSIVE"
        rec["reason"] = "replay_gate_failed"
    return rec


def run_case(exe: str, contexts: Path, out_dir: Path, name: str, case: dict[str, Any],
             thresholds: dict[str, float], timeout: int,
             factor: dict[str, Any] | None = None, modes: tuple[str, ...] = MODES) -> dict[str, dict[str, Any]]:
    context = contexts / name
    bad = check_context(context, case)
    if bad:
        return {m: {"verdict": "INCONCLUSIVE", "reason": bad} for m in modes}
    sites = None
    if factor is not None:
        sites = factor.get("sites") or []
        if not sites:
            reason = f"no_declared_factor:{factor.get('reason') or 'empty'}"
            return {m: {"verdict": "INCONCLUSIVE", "reason": reason} for m in modes}
    case_dir = out_dir / name
    case_dir.mkdir(parents=True, exist_ok=True)
    results = {}
    for mode in modes:
        out = case_dir / f"{mode}.json"
        args = build_args(exe, context, case, mode, out, thresholds, sites)
        started = time.perf_counter()
        try:
            proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
            err = None if proc.returncode == 0 else f"exit_{proc.returncode}"
            if err:
                (case_dir / f"{mode}.stderr.txt").write_text(proc.stderr[-20000:], encoding="utf-8")
        except subprocess.TimeoutExpired:
            err = "timeout"
        payload = None
        if err is None:
            try:
                payload = json.loads(out.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                err = "unreadable_output"
        rec = interpret(payload, mode, err)
        rec["wall_ms"] = round((time.perf_counter() - started) * 1000, 1)
        results[mode] = rec
    return results


def summarize(per_case: dict[str, dict[str, dict[str, Any]]], mode_list: tuple[str, ...] = MODES) -> dict[str, Any]:
    n = len(per_case)
    modes: dict[str, Any] = {}
    for mode in mode_list:
        recs = [c[mode] for c in per_case.values() if mode in c]
        verdicts = Counter(r["verdict"] for r in recs)
        reasons = Counter((r["reason"] or "?").split(":")[0] for r in recs if r["verdict"] == "INCONCLUSIVE")
        origins = Counter(r["revert_origin"] for r in recs if r.get("revert_origin"))
        entry: dict[str, Any] = {
            "n": len(recs),
            "verdicts": dict(sorted(verdicts.items())),
            "inconclusive_reasons": dict(sorted(reasons.items())),
            "revert_origin": dict(sorted(origins.items())),
        }
        if base_mode(mode) in ("whole-tx", "frame-local"):
            valid = len(recs) - verdicts.get("INCONCLUSIVE", 0)
            entry["valid"] = valid
            entry["valid_rate"] = round(valid / len(recs), 4) if recs else None
            entry["valid_rate_wilson95"] = wilson(valid, len(recs))
        else:
            passed, failed = verdicts.get("PASS", 0), verdicts.get("FAIL", 0)
            entry["applicable"] = passed + failed
            entry["pass"] = passed
            entry["pass_rate"] = round(passed / (passed + failed), 4) if passed + failed else None
            entry["pass_rate_wilson95"] = wilson(passed, passed + failed)
        modes[mode] = entry
    return {"n_cases": n, "modes": modes}


def short(rec: dict[str, Any]) -> str:
    v = rec.get("verdict", "?")
    if v == "INCONCLUSIVE":
        return f"INC({rec.get('reason') or '?'})"
    return v


def render_table(per_case: dict[str, dict[str, dict[str, Any]]], summary: dict[str, Any]) -> str:
    lines = []
    header = f"{'case':34} " + " ".join(f"{m:26}" for m in MODES)
    lines.append(header)
    lines.append("-" * len(header))
    for name, recs in per_case.items():
        label = name.replace("defihacklabs-", "")[:34]
        lines.append(f"{label:34} " + " ".join(f"{short(recs.get(m, {}))[:26]:26}" for m in MODES))
    lines.append("")
    for mode, e in summary["modes"].items():
        if "@" in mode:
            continue
        if "valid" in e:
            lines.append(f"{mode:12} valid {e['valid']}/{e['n']} CI95={e['valid_rate_wilson95']} "
                         f"verdicts={e['verdicts']} revert_origin={e['revert_origin']}")
        else:
            lines.append(f"{mode:12} pass {e['pass']}/{e['applicable']} CI95={e['pass_rate_wilson95']} "
                         f"verdicts={e['verdicts']}")
        if e["inconclusive_reasons"]:
            lines.append(f"{'':12} inconclusive: {e['inconclusive_reasons']}")
    dose = [m for m in summary["modes"] if "@" in m]
    if dose:
        abbrev = {"CAUSE": "C", "CAUSE_BLOCKED": "CB", "PARTIAL": "P", "NO_EFFECT": "NE", "INCONCLUSIVE": "-"}
        lines.append("")
        lines.append("dose-response (lambda: whole-tx/frame-local; C=CAUSE CB=CAUSE_BLOCKED P=PARTIAL NE=NO_EFFECT -=INC)")
        lams = sorted({m.split("@")[1] for m in dose}, key=float)
        lines.append(f"{'case':34} " + " ".join(f"{'l=' + lam:>10}" for lam in lams))
        for name, recs in per_case.items():
            if all((recs.get(f"whole-tx@{lam}", {}).get("reason") or "").startswith("no_declared_factor") for lam in lams):
                continue
            cells = []
            for lam in lams:
                w = abbrev.get(recs.get(f"whole-tx@{lam}", {}).get("verdict"), "?")
                f = abbrev.get(recs.get(f"frame-local@{lam}", {}).get("verdict"), "?")
                cells.append(f"{w + '/' + f:>10}")
            lines.append(f"{name.replace('defihacklabs-', '')[:34]:34} " + " ".join(cells))
        for m in dose:
            e = summary["modes"][m]
            lines.append(f"{m:18} valid {e['valid']}/{e['n']} verdicts={e['verdicts']} inconclusive={e['inconclusive_reasons']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--exe", help="built cmd/framelocal binary (required unless --render)")
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    ap.add_argument("--contexts", type=Path, default=DEFAULT_CONTEXTS)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--only", action="append", default=[], help="run only this case (repeatable)")
    ap.add_argument("--loss-min-frac", type=float, default=0.01)
    ap.add_argument("--rho", type=float, default=0.1)
    ap.add_argument("--timeout", type=int, default=900, help="seconds per run")
    ap.add_argument("--factors", type=Path, default=None,
                    help="frozen per-case factors from eval.rq3.discover_factors; without it the price-selector catalogue is used")
    ap.add_argument("--render", type=Path, default=None,
                    help="only re-print the tables from an existing summary.json")
    ap.add_argument("--dose", default="", help="comma-separated lambdas in (0,1) for dose-response, e.g. 0.25,0.5,0.75")
    args = ap.parse_args(argv)

    if args.render is not None:
        doc = json.loads(args.render.read_text(encoding="utf-8"))
        print(f"manifest sha256 {doc.get('manifest_sha256')}")
        print(render_table(doc["cases"], doc["summary"]))
        return 0
    if not args.exe:
        ap.error("--exe is required")
    args.out.mkdir(parents=True, exist_ok=True)
    manifest_sha = sha256_text(args.manifest)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    cases = manifest["cases"]
    if args.only:
        cases = {k: v for k, v in cases.items() if k in set(args.only)}
    thresholds = {"loss_min_frac": args.loss_min_frac, "rho": args.rho}
    lambdas = [float(x) for x in args.dose.split(",") if x.strip()]
    if any(not 0 < lam < 1 for lam in lambdas):
        raise SystemExit("--dose lambdas must be in (0, 1); lambda 1 is the plain run")
    mode_list = MODES + dose_modes(lambdas)
    factors = None
    if args.factors is not None:
        fdoc = json.loads(args.factors.read_text(encoding="utf-8"))
        if fdoc.get("manifest_sha256") != manifest_sha:
            raise SystemExit("factors were derived from a different manifest")
        factors = fdoc["cases"]
    lock = {"manifest": args.manifest.name, "manifest_sha256": manifest_sha, "n_cases": len(cases),
            "exe_sha256": sha256_file(Path(args.exe)), "thresholds": thresholds,
            "factors": args.factors.name if args.factors else None,
            "factors_sha256": sha256_text(args.factors) if args.factors else None,
            "dose_lambdas": lambdas,
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    (args.out / "manifest_lock.json").write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")

    per_case = {}
    for i, (name, case) in enumerate(sorted(cases.items()), 1):
        print(f"[{i}/{len(cases)}] {name}", file=sys.stderr, flush=True)
        factor = None if factors is None else factors.get(name, {"sites": [], "reason": "missing_from_factors"})
        per_case[name] = run_case(args.exe, args.contexts, args.out, name, case, thresholds, args.timeout, factor,
                                  mode_list)

    summary = summarize(per_case, mode_list)
    doc = {"schema": 1, **lock, "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "summary": summary, "cases": per_case}
    (args.out / "summary.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(f"manifest sha256 {manifest_sha}")
    print(render_table(per_case, summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
