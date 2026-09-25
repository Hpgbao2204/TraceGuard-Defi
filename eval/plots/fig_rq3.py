"""Fig. 5 (RQ3): naive vs gated attribution on the frozen 20-case queue, as three panels.

    python -m eval.plots.fig_rq3 --v2 .cache/rq3_final_v2/summary.json --v3 .cache/rq3_final_v3/summary.json --out paper/figures

Writes fig5a.pdf (decision cascade), fig5b.pdf (per-case evidence), fig5c.pdf (revert origin by mode).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

from .fig_rq1 import C_ATTACK, C_NEAR, C_ORD, INK, INK2, MUTED, ROOT, style  # noqa: E402

C_VICTIM, C_THIRD, C_PASS = C_ATTACK, C_NEAR, C_ORD
C_NONE = "#e6e5e0"
C_INC = "#b9b7b0"


def short(case: str) -> str:
    name = case.replace("defihacklabs-", "").rsplit("-", 3)[0]
    return {"exchangeissuance-index-coop": "exchangeissuance", "sizeflashloanlooping": "sizeflashloan",
            "unverified-6f7a": "unverified-6f7a"}.get(name, name)


def origin(rec) -> str:
    if not isinstance(rec, dict):
        return "none"
    if rec.get("reason", "") and "third_party" in str(rec.get("reason")):
        return "third_party"
    return rec.get("origin") or ("none" if rec.get("verdict") != "INCONCLUSIVE" else "none")


def panel_a(out: Path, v2, v3) -> None:
    stages = ["cases", "with factor", "victim revert\n(naive claim)", "security guard\n(strong)"]
    vals = {
        "rule v2": [20, v2["with_factor"], v2["coverage_valid"], v2["strong_evidence"]],
        "rule v3": [20, v3["with_factor"], v3["coverage_valid"], v3["strong_evidence"]],
    }
    fig, ax = plt.subplots(figsize=(1.45, 1.42))
    h = 0.36
    for j, (name, color) in enumerate([("rule v2", C_VICTIM), ("rule v3", C_THIRD)]):
        for i, v in enumerate(vals[name]):
            y = i + (j - 0.5) * h
            ax.barh(y, v, height=h * 0.9, color=color, lw=0, zorder=3)
            ax.text(v + 0.4, y, str(v), va="center", ha="left", fontsize=5.8, color=INK)
    ax.set_yticks(range(len(stages)))
    ax.set_yticklabels(stages, fontsize=5.8)
    ax.invert_yaxis()
    ax.set_xlim(0, 23)
    ax.set_xticks([0, 10, 20])
    ax.set_xlabel("Cases (of 20)")
    ax.tick_params(axis="y", length=0)
    ax.spines["left"].set_visible(False)
    ax.grid(True, axis="x", lw=0.3, color="#e6e5e0", zorder=0)
    ax.legend(handles=[Rectangle((0, 0), 1, 1, color=C_VICTIM), Rectangle((0, 0), 1, 1, color=C_THIRD)],
              labels=["rule v2 (frozen)", "rule v3 (declared)"], loc="lower right", frameon=False,
              fontsize=5.6, handlelength=1.0, borderaxespad=0.1)
    fig.savefig(out / "fig5a.pdf")
    plt.close(fig)


def panel_b(out: Path, rows_v2, rows_v3, totals_v2) -> None:
    v3_by_case = {r["case"]: r for r in rows_v3}
    rows = [r for r in rows_v2 if r.get("factor") not in (None, "-", "", [])]
    cols = ["U", "S", "FL", "I", "G", "v3"]
    fig, ax = plt.subplots(figsize=(1.22, 1.42))

    def cell(x, y, color, text, tcolor=INK):
        ax.add_patch(Rectangle((x - 0.46, y - 0.42), 0.92, 0.84, color=color, lw=0, zorder=2))
        ax.text(x, y, text, ha="center", va="center", fontsize=5.4, color=tcolor, zorder=3)

    def verdict_cell(rec):
        o = origin(rec)
        v = rec.get("verdict") if isinstance(rec, dict) else None
        if o == "victim" or v == "CAUSE_BLOCKED":
            return C_VICTIM, "V", "white"
        if o == "third_party":
            return C_THIRD, "T", "white"
        return C_INC, "–", INK

    for y, r in enumerate(rows):
        for x, key in enumerate(["unscoped", "scoped_whole_tx", "frame_local"]):
            color, text, tc = verdict_cell(r.get(key))
            cell(x, y, color, text, tc)
        iso = r.get("isolation")
        iso_v = iso.get("verdict") if isinstance(iso, dict) else iso
        cell(3, y, C_PASS if str(iso_v).upper().startswith("PASS") else C_INC, "P" if str(iso_v).upper().startswith("PASS") else "–")
        g = r.get("guard")
        gtype = g.get("type") if isinstance(g, dict) else None
        label = {"self_balance_consistency": "SB", "consistency": "SB", "unknown": "?",
                 "other": "SB", "security": "G"}.get(gtype, "–")
        cell(4, y, C_NONE, label)
        r3 = v3_by_case.get(r["case"], {})
        fin = str(r3.get("final", ""))
        if "CAUSE" in fin:
            cell(5, y, C_VICTIM, "V?", "white")
        elif "third_party" in fin:
            cell(5, y, C_THIRD, "T", "white")
        else:
            cell(5, y, C_NONE, "–")
    reasons = totals_v2["inconclusive_reasons"]
    n_nr = sum(v for k, v in reasons.items() if "no_read_changed" in k)
    n_hf = sum(v for k, v in reasons.items() if "no_harm_frame" in k)
    y = len(rows)
    ax.add_patch(Rectangle((-0.46, y - 0.42), len(cols) - 0.08, 0.84, color=C_NONE, lw=0, zorder=2))
    ax.text((len(cols) - 1) / 2, y, f"13 without a factor ({n_nr} + {n_hf})",
            ha="center", va="center", fontsize=5.0, color=INK, zorder=3)
    ax.set_xlim(-0.55, len(cols) - 0.45)
    ax.set_ylim(len(rows) + 0.6, -0.6)
    ax.set_xticks(range(len(cols)))
    ax.set_xticklabels(cols, fontsize=5.4)
    ax.xaxis.tick_top()
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([short(r["case"]) for r in rows], fontsize=5.6)
    ax.tick_params(length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    fig.savefig(out / "fig5b.pdf")
    plt.close(fig)


def panel_c(out: Path, totals_v2, rows_v2) -> None:
    fl = {"victim": 0, "third_party": 0}
    for r in rows_v2:
        if r.get("factor") in (None, "-", "", []):
            continue
        o = origin(r.get("frame_local"))
        if o in fl:
            fl[o] += 1
    modes = [("unscoped", totals_v2["revert_origin_with_factor"]["unscoped"]),
             ("read-scoped", totals_v2["revert_origin_with_factor"]["scoped_whole_tx"]),
             ("frame-local", fl)]
    fig, ax = plt.subplots(figsize=(1.18, 1.18))
    for i, (name, d) in enumerate(modes):
        left = 0
        for key, color in [("victim", C_VICTIM), ("third_party", C_THIRD), ("attacker", INK)]:
            v = d.get(key, 0)
            if v:
                ax.barh(i, v, left=left, height=0.55, color=color, lw=0, zorder=3)
                ax.text(left + v / 2, i, str(v), ha="center", va="center", fontsize=5.8, color="white", zorder=4)
                ax.plot([left + v, left + v], [i - 0.275, i + 0.275], color="white", lw=0.8, zorder=4)
                left += v
    ax.set_yticks(range(len(modes)))
    ax.set_yticklabels([m[0] for m in modes], fontsize=5.8)
    ax.invert_yaxis()
    ax.set_xlim(0, 7)
    ax.set_xticks([0, 7])
    ax.set_xlabel("Revert origin (7 factor cases)")
    ax.tick_params(axis="y", length=0)
    ax.spines["left"].set_visible(False)
    ax.legend(handles=[Rectangle((0, 0), 1, 1, color=c) for c in (C_VICTIM, C_THIRD, INK)],
              labels=["victim", "third party", "attacker (0)"], loc="lower center", bbox_to_anchor=(0.42, 1.0),
              ncol=3, frameon=False, fontsize=5.4, handlelength=0.9, columnspacing=0.6, handletextpad=0.3)
    fig.savefig(out / "fig5c.pdf")
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--v2", type=Path, default=ROOT / ".cache" / "rq3_final_v2" / "summary.json")
    ap.add_argument("--v3", type=Path, default=ROOT / ".cache" / "rq3_final_v3" / "summary.json")
    ap.add_argument("--out", type=Path, default=ROOT / "paper" / "figures")
    args = ap.parse_args()
    style()
    v2 = json.loads(args.v2.read_text(encoding="utf-8"))
    v3 = json.loads(args.v3.read_text(encoding="utf-8"))
    args.out.mkdir(parents=True, exist_ok=True)
    panel_a(args.out, v2["totals"], v3["totals"])
    panel_b(args.out, v2["rows"], v3["rows"], v2["totals"])
    panel_c(args.out, v2["totals"], v2["rows"])
    print("wrote", *(args.out / f"fig5{p}.pdf" for p in "abc"))


if __name__ == "__main__":
    main()
