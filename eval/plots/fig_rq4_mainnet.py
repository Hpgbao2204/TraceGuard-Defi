"""Fig. 7 (RQ4, mainnet): drop tests on historical sandwiches, replayed on the Go engine in builder hindsight.

    python -m eval.plots.fig_rq4_mainnet --out paper/figures

Reads .cache/revision/sandwich/results.json (eval.revision.mainnet_sandwich run; local only) and writes
  fig7a.pdf  per sandwich: the victim's relative shortfall when the front-run is dropped and when a placebo
             prefix transaction is dropped (symmetric-log axis), coloured by verdict, with delta = 10 bps;
  fig7b.pdf  per run (baseline, front-run drop, placebo drop): the engine's EVM time for the target and for
             the whole replayed prefix plus target, on the proof-bound mainnet contexts.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

from .fig_rq1 import C_ATTACK, C_NEAR, INK2, MUTED, ROOT, style

RESULTS = ROOT / ".cache" / "revision" / "sandwich" / "results.json"
DELTA = 0.001
PANEL_W, PANEL_H = 2.3, 1.55  # inches: 0.49 of the LNCS text width
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

    # Each panel is drawn at its printed width (0.49 of the LNCS text width), so the 7-8 pt style prints unscaled.
    # (a) shortfall strips: front-run drop vs placebo drop; the one inconclusive case per row is in the caption
    fig, ax = plt.subplots(figsize=(PANEL_W, PANEL_H))
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
        jitter = [(i % 5 - 2) * 0.06 for i in range(len(xs))]
        ax.scatter(xs, [y + j for j in jitter], s=14, c=cs, linewidths=0, alpha=0.9, zorder=3)
    ax.axvline(DELTA, color=INK2, lw=0.7, ls=(0, (3, 2)), zorder=1)
    ax.text(DELTA * 1.3, 0.5, r"$\delta$", color=INK2, ha="left", va="center")
    ax.set_xscale("symlog", linthresh=1e-4)
    ax.set_xlim(-0.2e-4, 0.3)
    ax.set_xticks([0, 1e-4, 1e-3, 1e-2, 1e-1])
    ax.set_yticks([0, 1], ["placebo", "front-run"])
    ax.set_ylim(-0.45, 1.45)
    ax.set_xlabel("victim shortfall (relative)")
    ax.legend(handles=[Line2D([], [], ls="", marker="o", ms=4.5, color=COLOR[k], label=k.replace("_", " ").lower())
                       for k in ("CAUSE", "NO_EFFECT")], loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=2,
              frameon=False, handletextpad=0.2, columnspacing=1.0)
    args.out.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out / "fig7a.pdf")
    plt.close(fig)

    # (b) engine cost on mainnet contexts: target EVM time and whole-context replay time per run
    runs_dir = args.results.parent / "runs"
    fig, ax = plt.subplots(figsize=(PANEL_W, PANEL_H))
    labels = [("base", "baseline"), ("drop_front", "front-run"), ("drop_placebo", "placebo")]
    for y, (stem, _) in enumerate(labels):
        tgt, rep = [], []
        for r in rows:
            # a placebo file without a placebo verdict is left over from an earlier placebo rule
            if stem == "drop_placebo" and (r.get("placebo_drop") or {}).get("verdict") in (None, "N/A"):
                continue
            f = runs_dir / r["victim_hash"] / f"{stem}.json"
            if f.is_file():
                t = json.loads(f.read_text(encoding="utf-8")).get("timing_ms") or {}
                if t.get("target_evm") is not None:
                    tgt.append(t["target_evm"])
                    rep.append(t.get("evm_replay"))
        jit = [(i % 5 - 2) * 0.05 for i in range(len(tgt))]
        ax.scatter(tgt, [y + 0.15 + j for j in jit], s=12, color=C_ATTACK, linewidths=0, alpha=0.85,
                   label="target" if y == 0 else None)
        ax.scatter([x for x in rep if x], [y - 0.15 + j for j, x in zip(jit, rep) if x], s=12, color=MUTED,
                   linewidths=0, alpha=0.85, label="prefix + target" if y == 0 else None)
    ax.set_xscale("log")
    ax.set_yticks(range(len(labels)), [lab for _, lab in labels])
    ax.set_ylim(-0.5, 2.5)
    ax.set_xlabel("EVM time per run (ms)")
    ax.legend(frameon=False, loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=2, handletextpad=0.2,
              columnspacing=1.0, markerscale=1.3)
    fig.savefig(args.out / "fig7b.pdf")
    plt.close(fig)
    print(f"wrote {args.out / 'fig7a.pdf'} and fig7b.pdf from {len(rows)} sandwiches")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
