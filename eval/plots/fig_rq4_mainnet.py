"""Fig. 7 (RQ4, mainnet): drop tests on historical sandwiches, replayed on the Go engine in builder hindsight.

    python -m eval.plots.fig_rq4_mainnet --out paper/figures

Reads .cache/revision/sandwich/results.json (eval.revision.mainnet_sandwich run; local only) and writes
  fig7a.pdf  per sandwich: the victim's relative shortfall when the front-run is dropped and when a placebo
             prefix transaction is dropped (symmetric-log axis), coloured by verdict, with delta = 10 bps;
  fig7b.pdf  per sandwich with a CAUSE verdict: relative shortfall against the number of transactions
             between front-run and victim, by pool kind (Uniswap V2 or V3).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

from .fig_rq1 import C_ATTACK, C_NEAR, INK, INK2, MUTED, ROOT, style  # noqa: E402

RESULTS = ROOT / ".cache" / "revision" / "sandwich" / "results.json"
DELTA = 0.001
COLOR = {"CAUSE": C_ATTACK, "NO_EFFECT": MUTED, "INCONCLUSIVE": C_NEAR}


def _rel(d: dict) -> float | None:
    return d.get("shortfall_rel")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", type=Path, default=RESULTS)
    ap.add_argument("--out", type=Path, default=ROOT / "paper" / "figures")
    args = ap.parse_args()
    style()
    rows = [r for r in json.loads(args.results.read_text(encoding="utf-8"))["rows"] if r.get("status") == "ok"]

    # (a) shortfall strips: front-run drop vs placebo drop
    fig, ax = plt.subplots(figsize=(3.3, 1.7))
    for y, key in ((1, "front_drop"), (0, "placebo_drop")):
        xs, cs, inc = [], [], 0
        for r in rows:
            d = r.get(key) or {}
            v = d.get("verdict")
            if v in ("CAUSE", "NO_EFFECT") and _rel(d) is not None:
                xs.append(max(_rel(d), 0.0))
                cs.append(COLOR[v])
            elif v == "INCONCLUSIVE":
                inc += 1
        jitter = [(i % 5 - 2) * 0.05 for i in range(len(xs))]
        ax.scatter(xs, [y + j for j in jitter], s=10, c=cs, linewidths=0, alpha=0.9, zorder=3)
        if inc:
            ax.text(1.02, y, f"{inc} inconclusive", transform=ax.get_yaxis_transform(), fontsize=6.5,
                    color=C_NEAR, va="center")
    ax.axvline(DELTA, color=INK2, lw=0.6, ls=(0, (3, 2)), zorder=1)
    ax.text(DELTA, 1.55, r"$\delta$ = 10 bps", fontsize=6.5, color=INK2, ha="center")
    ax.set_xscale("symlog", linthresh=1e-4)
    ax.set_xlim(-0.2e-4, 0.3)
    ax.set_yticks([0, 1], ["placebo\ndropped", "front-run\ndropped"])
    ax.set_ylim(-0.5, 1.7)
    ax.set_xlabel("victim shortfall / counterfactual output")
    ax.legend(handles=[Line2D([], [], ls="", marker="o", ms=4, color=COLOR[k], label=k.replace("_", " ").lower())
                       for k in ("CAUSE", "NO_EFFECT")], loc="lower right", frameon=False, handletextpad=0.2)
    args.out.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out / "fig7a.pdf")
    plt.close(fig)

    # (b) shortfall against the number of transactions between front-run and victim, by pool kind
    fig, ax = plt.subplots(figsize=(2.6, 1.7))
    for kind, marker in (("v2", "o"), ("v3", "s")):
        pts = [(r["victim"] - r["front"], _rel(r["front_drop"])) for r in rows
               if r["kind"] == kind and r["front_drop"].get("verdict") == "CAUSE" and _rel(r["front_drop"])]
        if pts:
            ax.scatter([p[0] for p in pts], [p[1] for p in pts], s=11, marker=marker, color=C_ATTACK if kind == "v2" else INK,
                       linewidths=0, alpha=0.85, label=f"Uniswap {kind.upper()}")
    ax.set_yscale("log")
    ax.axhline(DELTA, color=INK2, lw=0.6, ls=(0, (3, 2)))
    ax.set_xlabel("victim index $-$ front-run index")
    ax.set_ylabel("relative shortfall")
    ax.legend(frameon=False, loc="upper right", handletextpad=0.2)
    fig.savefig(args.out / "fig7b.pdf")
    plt.close(fig)
    print(f"wrote {args.out / 'fig7a.pdf'} and fig7b.pdf from {len(rows)} sandwiches")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
