"""Fig. 6 (RQ4) and the RQ4 table: builder-side sandwich prevention in simulation, pooled over seeds.

    python -m eval.plots.fig_rq4 --runs ".cache/mev_sim/seed*.json" --out paper/figures

  (a) fig6a.pdf  per sandwich bundle: victim harm measured by drop-replay vs the x*y=k ground truth;
  (b) fig6b.pdf  per bundle that reached layer 2: counterfactual harm by bundle kind (six sandwich variants,
                 benign back-runs and three shape lookalikes), colored by TraceGuard's decision, with the
                 exclusion counts of the shape heuristic and of TraceGuard (fail-closed) per kind.
Also writes .cache/mev_sim/rq4_table.json with pooled rates per builder mode.
"""
from __future__ import annotations

import argparse
import glob
import json
import math
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

from .fig_rq1 import C_ATTACK, C_NEAR, C_ORD, INK, INK2, MUTED, ROOT, style  # noqa: E402

C_EXCL, C_DEF, C_INCL = C_ATTACK, C_NEAR, "#b9b7b0"
DEC_COLOR = {"EXCLUDE": C_EXCL, "DEFAULT": C_DEF, "INCLUDE": C_INCL}
VARIANTS = ["classic", "split", "addr_swap", "aggregator", "multipool", "decoy"]
BENIGN = ["arb_backrun", "jit", "mm_reverse", "xpool"]


def wilson(k: int, n: int) -> list[float]:
    if not n:
        return [0.0, 0.0]
    z, p = 1.959963984540054, k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0.0, c - h), 4), round(min(1.0, c + h), 4)]


def bundles(run: dict, mode: str) -> list[dict]:
    return [b for s in run["slots"][mode] for b in s["bundles"]]


def kind_of(b: dict) -> str:
    return b["variant"] if b["attack"] else b["kind"]


def table(runs: list[dict]) -> dict:
    out = {}
    for mode in runs[0]["slots"]:
        sand = [b for r in runs for b in bundles(r, mode) if b["attack"] and b["status"] in ("included", "excluded")]
        ben = [b for r in runs for b in bundles(r, mode) if not b["attack"] and b["status"] in ("included", "excluded")]
        ks, kb = sum(b["status"] == "excluded" for b in sand), sum(b["status"] == "excluded" for b in ben)
        avoided = [r["summary"][mode].get("victim_harm_avoided_pct") for r in runs]
        avoided = [a for a in avoided if a is not None]
        match = [r["summary"][mode]["layer2_harm_equals_ground_truth"] for r in runs]
        out[mode] = {"sandwich_excluded": [ks, len(sand), wilson(ks, len(sand))],
                     "benign_excluded": [kb, len(ben), wilson(kb, len(ben))],
                     "harm_avoided_pct_mean": round(float(np.mean(avoided)), 2) if avoided else None,
                     "harm_avoided_pct_range": [min(avoided), max(avoided)] if avoided else None,
                     "l2_equals_ground_truth": [sum(m["match"] for m in match), sum(m["n"] for m in match)]}
    return out


POLICIES = [  # (mode, label, colour, linestyle)
    ("none", "no filter", MUTED, (0, (3, 2))),
    ("heur_strict", "strict heuristic", C_ORD, "-"),
    ("heur_naive", "shape heuristic", C_NEAR, "-"),
    ("l1_only", "layer 1 only", INK, (0, (1, 1.5))),
    ("tg_open", "TG fail-open", C_ATTACK, (0, (4, 1.5))),
    ("tg_closed", "TG fail-closed", C_ATTACK, "-"),
]


def per_slot(run: dict, mode: str, what: str) -> np.ndarray:
    """Per-slot series: victim harm landed (token A) or benign bundles excluded."""
    vals = []
    for s in run["slots"][mode]:
        if what == "harm":
            vals.append(sum(b["gt_harm_a"] or 0.0 for b in s["bundles"] if b["attack"] and b["status"] == "included"))
        else:
            vals.append(sum(1 for b in s["bundles"] if not b["attack"] and b["status"] == "excluded"))
    return np.array(vals, float)


def cumulative_panel(out: Path, runs: list[dict], what: str, fname: str, ylabel: str, modes) -> None:
    fig, ax = plt.subplots(figsize=(1.9, 2.1))
    x = np.arange(1, len(runs[0]["slots"]["none"]) + 1)
    ends = []
    for mode, label, color, ls in POLICIES:
        if mode not in modes:
            continue
        cum = np.array([np.cumsum(per_slot(r, mode, what)) for r in runs])
        med, lo, hi = np.median(cum, 0), cum.min(0), cum.max(0)
        ax.fill_between(x, lo, hi, color=color, alpha=0.15, lw=0, zorder=1)
        ax.plot(x, med, color=color, ls=ls, lw=1.3, zorder=3)
        ends.append([med[-1], label, color])
    ends.sort(key=lambda e: e[0])
    top = max(e[0] for e in ends) or 1.0
    groups = []  # lines ending at (almost) the same value share one label
    for y, label, color in ends:
        if groups and abs(y - groups[-1][0]) < 0.02 * top:
            groups[-1][1].append(label)
        else:
            groups.append([y, [label]])
    last_top = -1e9
    line_h = 0.065 * top
    for y, labels in groups:  # direct labels at the right end, nudged upward only when they collide
        half = len(labels) * line_h / 2
        y = max(y, last_top + half)
        last_top = y + half
        ax.text(x[-1] * 1.02, y, "\n".join(labels), fontsize=6.5, color=INK, va="center", ha="left",
                linespacing=1.0)
    ax.set_xlim(0, x[-1])
    ax.set_ylim(0, top * 1.08)
    ax.set_xlabel("Slot")
    ax.set_ylabel(ylabel, labelpad=1)
    ax.grid(True, lw=0.3, color="#e6e5e0", zorder=0)
    fig.savefig(out / fname)
    plt.close(fig)


def panel_a(out: Path, runs: list[dict]) -> None:
    cumulative_panel(out, runs, "harm", "fig6a.pdf", "Cumulative victim harm (token A)",
                     {"none", "heur_strict", "heur_naive", "tg_open", "tg_closed"})


def panel_b(out: Path, runs: list[dict]) -> None:
    cumulative_panel(out, runs, "benign", "fig6b.pdf", "Cumulative benign bundles excluded",
                     {"heur_strict", "heur_naive", "l1_only", "tg_open", "tg_closed"})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default=str(ROOT / ".cache" / "mev_sim" / "seed*.json"))
    ap.add_argument("--out", type=Path, default=ROOT / "paper" / "figures")
    ap.add_argument("--table", type=Path, default=ROOT / ".cache" / "mev_sim" / "rq4_table.json")
    args = ap.parse_args()
    runs = [json.loads(Path(f).read_text(encoding="utf-8")) for f in sorted(glob.glob(args.runs))]
    style()
    args.out.mkdir(parents=True, exist_ok=True)
    tab = table(runs)
    engines = sorted({r["config"].get("l2_engine", "anvil") for r in runs})
    geth = {}
    for r in runs:  # pooled layer-2-on-geth-replay checks (only runs with --l2-engine geth)
        for m, s in r["summary"].items():
            g = s.get("geth_replay")
            if g:
                acc = geth.setdefault(m, {"evaluated": 0, "gate": 0, "verdict_equals_anvil": 0, "harm_equals_anvil": 0})
                acc["evaluated"] += g["evaluated"]
                acc["gate"] += g["baseline_gate"]["k"]
                acc["verdict_equals_anvil"] += g["verdict_equals_anvil"]["k"]
                acc["harm_equals_anvil"] += g["harm_equals_anvil"]["k"]
    args.table.write_text(json.dumps({"seeds": [r["config"]["seed"] for r in runs], "l2_engine": engines,
                                      "geth_replay": geth, "modes": tab}, indent=1), encoding="utf-8")
    print(f"layer-2 engine: {', '.join(engines)}")
    for m, g in geth.items():
        print(f"{m:12s} geth-replay gate {g['gate']}/{g['evaluated']} verdict=anvil "
              f"{g['verdict_equals_anvil']}/{g['evaluated']} harm=anvil {g['harm_equals_anvil']}/{g['evaluated']}")
    panel_a(args.out, runs)
    panel_b(args.out, runs)
    for m, v in tab.items():
        print(f"{m:12s} sandwich {v['sandwich_excluded'][:2]} benign {v['benign_excluded'][:2]} "
              f"avoided {v['harm_avoided_pct_mean']}% l2=gt {v['l2_equals_ground_truth']}")


if __name__ == "__main__":
    main()
