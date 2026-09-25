"""Fig. 4 (RQ2): replay fidelity and cost, drawn as two panels.

    python -m eval.plots.fig_rq2 --out paper/figures

  (a) fig4a.pdf  gas used by authenticated replay vs an independent Nethermind node, one point per frozen case,
                 marker area by same-block prefix length; all points also match on status, logs hash, post-state.
  (b) fig4b.pdf  lean-mode target execution time, every repeated run of every case, with the full-trace
                 single runs and builder reference budgets.

Inputs (local, git-ignored): eval/results/m4/m4_b2_vs_liquify_20.json, .cache/rq2/latency.json.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

from .fig_rq1 import C_ATTACK, C_NEAR, INK, INK2, MUTED, ROOT, style  # noqa: E402
from .fig_rq3 import short  # noqa: E402

# Full-trace target_evm (ms), single runs on 25 Sep 2026 (paper Table: replay cost, "Full trace" row).
FULL_TRACE_MS = {"defihacklabs-fixedtokenbswap-2025-06-15": 1566.8,
                 "defihacklabs-alkemiearn-2026-03-10": 1617.4,
                 "defihacklabs-exchangeissuance-index-coop-2026-07-30": 1633.4}


def area(prefix: int) -> float:
    """Marker area (pt^2) for a same-block prefix length; shared by points and legend."""
    return 6 + 3.5 * np.sqrt(prefix)


def panel_a(out: Path, fid: dict, lat: dict) -> None:
    fig, ax = plt.subplots(figsize=(2.3, 2.3))
    xs, ys, sizes, match = [], [], [], []
    for name, v in fid.items():
        b, n = v["b2"], v["independent"]
        xs.append(n["gas_used"])
        ys.append(b["gas_used"])
        prefix = (lat.get(name, {}).get("n_tx") or 1) - 1
        sizes.append(area(prefix))
        match.append(all(b[k] == n[k] for k in ("gas_used", "logs_hash", "relevant_state_hash", "status")))
    lo, hi = 1e4, 3e7
    ax.plot([lo, hi], [lo, hi], color=MUTED, lw=0.7, ls=(0, (3, 2)), zorder=1)
    ax.scatter(xs, ys, s=sizes, facecolor=C_ATTACK, edgecolor="white", lw=0.6, alpha=0.85, zorder=3)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlim(lo, hi)
    ax.set_ylim(lo, hi)
    ax.set_xlabel("Nethermind gas")
    ax.set_ylabel("Replay gas", labelpad=1)
    ax.text(0.97, 0.04, f"exact match\n{sum(match)}/{len(match)}", transform=ax.transAxes, fontsize=7,
            color=INK, va="bottom", ha="right")
    ax.grid(True, lw=0.3, color="#e6e5e0", zorder=0)
    ax.legend(handles=[Line2D([], [], ls="", marker="o", ms=np.sqrt(area(k)), color=C_ATTACK, mec="white")
                       for k in (0, 30, 1000)],
              labels=["prefix 0", "prefix 30", "prefix 1,000"], loc="upper left", frameon=False, fontsize=7,
              handletextpad=0.2, labelspacing=0.6, borderaxespad=0.2)
    fig.savefig(out / "fig4a.pdf")
    plt.close(fig)


def panel_b(out: Path, lat: dict) -> None:
    cases = sorted(lat, key=lambda n: lat[n]["target_median_ms"])
    fig, ax = plt.subplots(figsize=(2.05, 2.9))
    rng = np.random.default_rng(5)
    for y, name in enumerate(cases):
        vals = [r["target_evm"] for r in lat[name]["runs"] if r.get("target_evm")]
        ax.scatter(vals, y + rng.uniform(-0.18, 0.18, len(vals)), s=5, color=C_ATTACK, alpha=0.55, lw=0, zorder=3)
        ax.plot(np.median(vals), y, "|", ms=6, mew=1.3, color=INK, zorder=4)
        if name in FULL_TRACE_MS:
            ax.plot(FULL_TRACE_MS[name], y, "o", ms=4.2, mfc="white", mec=C_NEAR, mew=0.9, zorder=4)
    for x, lab in ((500, "500 ms"), (12000, "12 s slot")):
        ax.axvline(x, color=INK2, lw=0.6, ls=(0, (3, 2)), zorder=1)
        ax.text(x * 0.85, len(cases) - 0.6, lab, fontsize=6.5, color=INK2, rotation=90, ha="right", va="bottom")
    ax.set_xscale("log")
    ax.set_xlim(0.4, 2.5e4)
    ax.set_ylim(len(cases) - 0.5, -0.6)
    ax.set_yticks(range(len(cases)))
    ax.set_yticklabels([short(n) for n in cases], fontsize=7)
    ax.set_xlabel("Target execution time (ms)")
    ax.tick_params(axis="y", length=0)
    ax.spines["left"].set_visible(False)
    ax.grid(True, axis="x", lw=0.3, color="#e6e5e0", zorder=0)
    ax.legend(handles=[Line2D([], [], ls="", marker="o", ms=3, color=C_ATTACK),
                       Line2D([], [], ls="", marker="|", ms=6, mew=1.3, color=INK),
                       Line2D([], [], ls="", marker="o", ms=4.2, mfc="white", mec=C_NEAR)],
              labels=["lean run", "median", "full trace"], loc="lower center", bbox_to_anchor=(0.45, 1.0),
              ncol=3, frameon=False, fontsize=7, handletextpad=0.2, columnspacing=0.8, borderaxespad=0.1)
    fig.savefig(out / "fig4b.pdf")
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fidelity", type=Path, default=ROOT / "eval" / "results" / "m4" / "m4_b2_vs_liquify_20.json")
    ap.add_argument("--latency", type=Path, default=ROOT / ".cache" / "rq2" / "latency.json")
    ap.add_argument("--out", type=Path, default=ROOT / "paper" / "figures")
    args = ap.parse_args()
    style()
    fid = json.loads(args.fidelity.read_text(encoding="utf-8"))
    lat = json.loads(args.latency.read_text(encoding="utf-8"))["cases"]
    args.out.mkdir(parents=True, exist_ok=True)
    panel_a(args.out, fid, lat)
    panel_b(args.out, lat)
    print("wrote", *(args.out / f"fig4{p}.pdf" for p in "ab"))


if __name__ == "__main__":
    main()
