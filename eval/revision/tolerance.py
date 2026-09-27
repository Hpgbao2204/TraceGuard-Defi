"""Sensitivity of the verdicts to the tolerances of Eq. 7 (epsilon, rho) and of the drop test (delta).

    python -m eval.revision.tolerance sim        # rerun the RQ4 simulation per delta (anvil, ~15 min)
    python -m eval.revision.tolerance analyze    # write .cache/revision/tolerance.json

epsilon (loss_min_frac) and rho enter only the per-token classification of a comparable, non-reverting
run, so the RQ3 runs (frozen and amended boundaries, rules v2 and v3, guard restorations) are
reclassified offline from their stored per-token losses with the same rule as cmd/framelocal
(perTokenVerdict). delta enters the drop test: the mainnet sandwiches are reclassified from the stored
victim output and shortfall; the simulation is rerun per delta, because a changed decision changes the
blocks that later slots build on.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import Counter
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / ".cache"
RQ3_RUNS = {
    "frozen_v2": CACHE / "rq3_final_v2_new" / "runs.json",
    "frozen_v3": CACHE / "rq3_final_v3_new" / "runs.json",
    "amended_v2": CACHE / "rq3_final_amended_v2" / "runs.json",
    "amended_v3": CACHE / "rq3_final_amended_v3" / "runs.json",
}
GUARD_RUNS = CACHE / "rq3_guard"
SANDWICH = CACHE / "revision" / "sandwich" / "results.json"
SIM_DIR = CACHE / "revision" / "tolerance_sim"
SIM_BASE = CACHE / "mev_sim"
OUT = CACHE / "revision" / "tolerance.json"

EPSILONS = (0.001, 0.01, 0.05)
RHOS = (0.05, 0.1, 0.2)
DELTAS = (0.0005, 0.001, 0.003)  # 5, 10, 30 basis points
DEFAULT = (0.01, 0.1, 0.001)
SEEDS = (1, 2, 3, 4, 5)
TOKEN_VERDICTS = ("CAUSE", "PARTIAL", "NO_EFFECT")


def per_token_verdict(losses: list[dict], eps: float, rho: float) -> str | None:
    """cmd/framelocal perTokenVerdict on stored losses; None if no token was harmed at baseline."""
    lmin, keep = Fraction(eps), Fraction(1) - Fraction(rho)
    outcomes, harmed = Counter(), 0
    for t in losses:
        base, cf = int(t["baseline"]), int(t["counterfactual"])
        if base <= 0:
            if cf > 0:
                outcomes["NEW_HARM"] += 1
            continue
        harmed += 1
        if cf <= base * lmin:
            outcomes["CAUSE"] += 1
        elif cf <= base * keep:
            outcomes["PARTIAL"] += 1
        else:
            outcomes["NO_EFFECT"] += 1
    if harmed == 0:
        return None
    if outcomes["CAUSE"] == harmed and outcomes["NEW_HARM"] == 0:
        return "CAUSE"
    if outcomes["NO_EFFECT"] == harmed:
        return "NO_EFFECT"
    return "PARTIAL"


def _token_runs():
    """(source, case, mode, record) for every stored run whose verdict came from per-token losses."""
    for src, path in RQ3_RUNS.items():
        for case, recs in json.loads(path.read_text(encoding="utf-8"))["cases"].items():
            for mode, rec in recs.items():
                if rec.get("verdict") in TOKEN_VERDICTS and rec.get("token_losses"):
                    yield src, case, mode, rec
    for path in sorted(GUARD_RUNS.glob("*/*.json")):
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if isinstance(rec, dict) and rec.get("verdict") in TOKEN_VERDICTS and rec.get("token_losses"):
            yield "guard", path.parent.name, path.stem, rec


def rq3_sensitivity() -> dict:
    runs = list(_token_runs())
    check = [per_token_verdict(r["token_losses"], *DEFAULT[:2]) == r["verdict"] for *_, r in runs]
    grid = []
    for eps in EPSILONS:
        for rho in RHOS:
            flips = []
            counts = Counter()
            for src, case, mode, rec in runs:
                v = per_token_verdict(rec["token_losses"], eps, rho)
                counts[v] += 1
                if v != rec["verdict"]:
                    flips.append({"source": src, "case": case, "mode": mode, "from": rec["verdict"], "to": v})
            main_axis = [f for f in flips if f["mode"] in ("whole-tx", "frame-local")]
            grid.append({"epsilon": eps, "rho": rho, "verdicts": dict(counts), "flips": len(flips),
                         "flips_main_axis": len(main_axis), "flipped": flips})
    return {"n_runs": len(runs), "n_main_axis": sum(m in ("whole-tx", "frame-local") for _, _, m, _ in runs),
            "default_reproduced": all(check), "by_source": dict(Counter(s for s, *_ in runs)),
            "baseline_verdicts": dict(Counter(r["verdict"] for *_, r in runs)), "grid": grid}


def mainnet_sensitivity() -> dict:
    rows = [r for r in json.loads(SANDWICH.read_text(encoding="utf-8"))["rows"] if r.get("status") == "ok"]
    out = {}
    for delta in DELTAS:
        res = {}
        for key in ("front_drop", "placebo_drop"):
            c = Counter()
            for r in rows:
                d = r[key]
                if d.get("verdict") in ("CAUSE", "NO_EFFECT") and d.get("out_cf") is not None:
                    c["CAUSE" if d["shortfall"] >= delta * d["out_cf"] else "NO_EFFECT"] += 1
                else:
                    c[d.get("verdict")] += 1
            res[key] = dict(c)
        out[f"{delta * 1e4:g}bps"] = res
    return out


def _sim_path(seed: int, delta: float) -> Path:
    return SIM_DIR / f"seed{seed}_d{delta * 1e4:g}bps.json"


def cmd_sim(args) -> None:
    SIM_DIR.mkdir(parents=True, exist_ok=True)
    anvil = args.anvil or os.environ.get("ANVIL") or str(Path.home() / ".foundry" / "bin" / "anvil.exe")
    for delta in DELTAS:  # the default delta too, as a reproduction check of the paper's runs
        for seed in SEEDS:
            out = _sim_path(seed, delta)
            if out.is_file():
                continue
            cmd = [sys.executable, "-m", "eval.mev_sim.run", "--slots", "200", "--seed", str(seed),
                   "--modes", "tg_open,tg_closed", "--rel-threshold", str(delta), "--out", str(out),
                   "--anvil", anvil]
            print(" ".join(cmd), flush=True)
            subprocess.run(cmd, check=True, cwd=ROOT)


def sim_sensitivity() -> dict:
    out = {}
    for delta in DELTAS:
        per_mode: dict = {}
        for seed in SEEDS:
            path = _sim_path(seed, delta)
            if not path.is_file():
                per_mode = {"missing": str(path.relative_to(ROOT))}
                break
            summ = json.loads(path.read_text(encoding="utf-8"))["summary"]
            for mode in ("tg_open", "tg_closed"):
                s = summ[mode]
                m = per_mode.setdefault(mode, Counter())
                m["sandwich_k"] += s["sandwich_blocked"]["k"]
                m["sandwich_n"] += s["sandwich_blocked"]["n"]
                m["benign_k"] += s["benign_blocked"]["k"]
                m["benign_n"] += s["benign_blocked"]["n"]
                # harm avoided against the paper's no-policy run of the same seed (same order flow)
                none = json.loads((SIM_BASE / f"seed{seed}.json").read_text(encoding="utf-8"))["summary"]["none"]
                m["harm_avoided_pct_sum"] += 100 * (1 - s["victim_harm_realized_A"] / none["victim_harm_realized_A"])
                for v, n in (s.get("verdicts") or {}).items():
                    m[f"verdict:{v}"] += n
        for mode, m in per_mode.items():
            if isinstance(m, Counter):
                m = dict(m)
                m["sandwich_rate"] = m["sandwich_k"] / m["sandwich_n"]
                m["benign_rate"] = m["benign_k"] / m["benign_n"]
                m["harm_avoided_pct_mean"] = m.pop("harm_avoided_pct_sum") / len(SEEDS)
                per_mode[mode] = m
        out[f"{delta * 1e4:g}bps"] = per_mode
    # the paper's runs (SIM_BASE, all six modes) against the rerun at the default delta
    repro = {}
    for seed in SEEDS:
        a, b = SIM_BASE / f"seed{seed}.json", _sim_path(seed, DEFAULT[2])
        if a.is_file() and b.is_file():
            sa, sb = (json.loads(x.read_text(encoding="utf-8"))["summary"] for x in (a, b))
            repro[seed] = {m: {k: sa[m][k] == sb[m][k] for k in ("sandwich_blocked", "benign_blocked", "verdicts")}
                           for m in ("tg_open", "tg_closed")}
    out["default_reproduces_paper_runs"] = repro
    return out


def cmd_analyze(args) -> None:
    res = {"rq3": rq3_sensitivity(), "mainnet": mainnet_sensitivity(), "simulation": sim_sensitivity()}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, indent=1), encoding="utf-8")
    brief = {**res, "rq3": {k: v for k, v in res["rq3"].items() if k != "grid"}}
    brief["rq3"]["grid"] = [{k: g[k] for k in ("epsilon", "rho", "verdicts", "flips", "flips_main_axis")}
                            for g in res["rq3"]["grid"]]
    print(json.dumps(brief, indent=1))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sm = sub.add_parser("sim")
    sm.add_argument("--anvil", default=None)
    sub.add_parser("analyze")
    args = ap.parse_args()
    {"sim": cmd_sim, "analyze": cmd_analyze}[args.cmd](args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
