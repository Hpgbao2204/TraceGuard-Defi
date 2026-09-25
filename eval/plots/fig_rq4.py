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

from .fig_rq1 import C_ATTACK, C_NEAR, INK, INK2, MUTED, ROOT, style  # noqa: E402

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


def panel_a(out: Path, runs: list[dict]) -> None:
    fig, ax = plt.subplots(figsize=(2.15, 2.15))
    pts = defaultdict(list)
    for r in runs:
        for b in bundles(r, "tg_closed"):
            if b["attack"] and b.get("gt_harm") and b.get("harm_l2") is not None and b["verdict"]:
                pts[b["decision"] or "INCLUDE"].append((float(b["gt_harm"]) / 1e18,
                                                        max(float(b["harm_l2"]), 1.0) / 1e18))
    allv = [v for p in pts.values() for xy in p for v in xy]
    lo, hi = 10 ** math.floor(math.log10(min(allv))), 10 ** math.ceil(math.log10(max(allv)))
    ax.plot([lo, hi], [lo, hi], color=MUTED, lw=0.7, ls=(0, (3, 2)), zorder=1)
    for dec in ("EXCLUDE", "DEFAULT", "INCLUDE"):
        if pts.get(dec):
            x, y = zip(*pts[dec])
            ax.scatter(x, y, s=9, color=DEC_COLOR[dec], alpha=0.6, lw=0, zorder=4 if dec == "EXCLUDE" else 3,
                       label=dec.lower())
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlim(lo, hi)
    ax.set_ylim(lo, hi)
    ax.set_xlabel("Ground-truth harm (tokens)")
    ax.set_ylabel("Replayed harm (tokens)", labelpad=1)
    n = sum(len(p) for p in pts.values())
    exact = sum(1 for p in pts.values() for x, y in p if x == y)
    ax.text(0.97, 0.04, f"exact {exact}/{n}", transform=ax.transAxes, fontsize=7, color=INK, ha="right",
            va="bottom")
    ax.grid(True, lw=0.3, color="#e6e5e0", zorder=0)
    ax.legend(loc="upper left", frameon=False, fontsize=7, handletextpad=0.1, borderaxespad=0.2,
              markerscale=1.6)
    fig.savefig(out / "fig6a.pdf")
    plt.close(fig)


def panel_b(out: Path, runs: list[dict]) -> None:
    rows = VARIANTS + BENIGN
    fig, ax = plt.subplots(figsize=(1.95, 2.9))
    rng = np.random.default_rng(11)
    heur = defaultdict(lambda: [0, 0])
    tg = defaultdict(lambda: [0, 0])
    for r in runs:
        for mode, acc in (("heur_naive", heur), ("tg_closed", tg)):
            for b in bundles(r, mode):
                if b["status"] in ("included", "excluded"):
                    acc[kind_of(b)][0] += b["status"] == "excluded"
                    acc[kind_of(b)][1] += 1
        for b in bundles(r, "tg_closed"):
            k = kind_of(b)
            if k not in rows or not b["verdict"]:
                continue
            harm = float(b.get("harm_l2") or 0) / 1e18
            x = harm if harm > 1e-9 else 3e-10
            ax.scatter(x, rows.index(k) + rng.uniform(-0.28, 0.28), s=6, lw=0, alpha=0.55,
                       color=DEC_COLOR.get(b["decision"] or "INCLUDE", C_INCL), zorder=3)
    for i, k in enumerate(rows):
        h, t = heur[k], tg[k]
        ax.text(4e1, i, f"{h[0]}/{h[1]}  {t[0]}/{t[1]}", fontsize=6.5, color=INK, va="center", ha="left")
    ax.text(4e1, -1.0, "excluded: heur.   TG", fontsize=6.5, color=INK2, va="bottom", ha="left")
    ax.axvspan(1.5e-10, 6e-10, color="#f1f0ec", lw=0, zorder=0)
    ax.axhline(len(VARIANTS) - 0.5, color=INK2, lw=0.5, ls=(0, (2, 2)))
    ax.set_xscale("log")
    ax.set_xlim(1.5e-10, 2e1)
    ax.set_xticks([1e-8, 1e-4, 1e0])
    ax.set_ylim(len(rows) - 0.5, -0.8)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([k.replace("_", " ") for k in rows], fontsize=7)
    ax.set_xlabel("Counterfactual harm (tokens)")
    ax.tick_params(axis="y", length=0)
    ax.spines["left"].set_visible(False)
    ax.grid(True, axis="x", lw=0.3, color="#e6e5e0", zorder=0)
    ax.legend(handles=[Line2D([], [], ls="", marker="o", ms=4, color=DEC_COLOR[d]) for d in ("EXCLUDE", "DEFAULT", "INCLUDE")],
              labels=["exclude", "default", "include"], loc="lower center", bbox_to_anchor=(0.35, 1.04), ncol=3,
              frameon=False, fontsize=7, handletextpad=0.1, columnspacing=0.6, borderaxespad=0.0)
    fig.savefig(out / "fig6b.pdf")
    plt.close(fig)


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
    args.table.write_text(json.dumps({"seeds": [r["config"]["seed"] for r in runs], "modes": tab}, indent=1),
                          encoding="utf-8")
    panel_a(args.out, runs)
    panel_b(args.out, runs)
    for m, v in tab.items():
        print(f"{m:12s} sandwich {v['sandwich_excluded'][:2]} benign {v['benign_excluded'][:2]} "
              f"avoided {v['harm_avoided_pct_mean']}% l2=gt {v['l2_equals_ground_truth']}")


if __name__ == "__main__":
    main()
