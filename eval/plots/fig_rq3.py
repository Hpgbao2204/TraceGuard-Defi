"""Fig. 5 (RQ3): what a counterfactual rule sees inside 20 exploit transactions, drawn as three panels.

    python -m eval.plots.fig_rq3 --out paper/figures

The unit of analysis is the victim read and the victim call frame, not the case:
  (a) fig5a.pdf  every read made by the victim inside a harm frame (n = 795), placed by how much its value
                 changed between S0 and harm-frame entry, grouped by what the read is, marked by factor rule;
  (b) fig5b.pdf  execution raster of all 20 transactions: victim entry frames, harm frames, and changed reads
                 on a normalized execution clock;
  (c) fig5c.pdf  flow of the seven v2 factor cases' revert origin from unscoped to read-scoped to frame-local.

Inputs (local, git-ignored): .cache/rq3_discover/*.json, eval/rq3/fixed20_factors{,_v3}.json,
.cache/rq3_final_v2/summary.json.
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
from matplotlib.patches import Polygon, Rectangle  # noqa: E402

from .fig_rq1 import C_ATTACK, C_NEAR, C_ORD, INK, INK2, MUTED, ROOT, style  # noqa: E402

C_V3, C_V2, C_PASSIVE = C_ATTACK, C_NEAR, "#b9b7b0"
C_VICTIM, C_THIRD = C_ATTACK, C_NEAR

GROUPS = [
    ("balance", {"0x70a08231"}),
    ("price, accounting", {"0x0902f1ac", "0xfeaf968c", "0x50d25bcd", "0x3850c7bd", "0xfc57d4fc", "0x182df0f5",
                            "0xbd6d894d", "0x01e1d114", "0x07a2d13a", "0x18160ddd", "0x98d5fdca", "0x41976e09"}),
    ("token call", {"0xa9059cbb", "0x23b872dd", "0x095ea7b3", "0xdd62ed3e"}),
    ("metadata", {"0x95d89b41", "0x313ce567", "0x06fdde03", "0x6f307dc3", "0x01ffc9a7"}),
    ("other", None),
]
NAMED = {"getReserves()": "0x0902f1ac", "latestRoundData()": "0xfeaf968c", "latestAnswer()": "0x50d25bcd",
         "slot0()": "0x3850c7bd", "balanceOf(address)": "0x70a08231"}


def short(case: str) -> str:
    name = case.replace("defihacklabs-", "").rsplit("-", 3)[0]
    return {"exchangeissuance-index-coop": "exchangeissuance", "sizeflashloanlooping": "sizeflashloan",
            "strategyllamalendconvex": "llamalendconvex", "unistreetlaunchpad": "unistreet"}.get(name, name)


def word(hexstr: str | None) -> int | None:
    h = (hexstr or "")[2:]
    if len(h) < 64:
        return None
    return int(h[:64], 16)


def group_of(sel: str) -> int:
    sel = NAMED.get(sel, sel).lower()
    for i, (_, sels) in enumerate(GROUPS):
        if sels is not None and sel in sels:
            return i
    return len(GROUPS) - 1


def load(discover: Path):
    cases = {}
    for f in sorted(discover.glob("*.json")):
        cases[f.stem] = json.loads(f.read_text(encoding="utf-8"))
    return cases


def factor_sites(path: Path) -> dict[str, set[str]]:
    d = json.loads(path.read_text(encoding="utf-8"))["cases"]
    return {k: {s.lower() for s in (v.get("sites") or [])} for k, v in d.items()}


def panel_a(out: Path, cases, f2, f3) -> None:
    rng = np.random.default_rng(3)
    fig, ax = plt.subplots(figsize=(1.30, 1.95))
    counts = np.zeros((len(GROUPS), 2), int)
    for name, d in cases.items():
        for r in d.get("scoped_reads") or []:
            g = group_of(r.get("selector") or "")
            v0, ve = word(r.get("v0_value")), word(r.get("observed_value"))
            changed = v0 is not None and ve is not None and v0 != ve
            counts[g, 0] += 1
            counts[g, 1] += changed
            x = abs(ve - v0) / max(v0, 1) if changed else 3e-7
            x = min(max(x, 1e-6), 1e3) if changed else x
            site = f"{(r.get('target') or '').lower()}:{NAMED.get(r.get('selector'), r.get('selector') or '').lower()}"
            if site in f3.get(name, set()):
                color, size, z = C_V3, 11, 5
            elif site in f2.get(name, set()):
                color, size, z = C_V2, 11, 4
            else:
                color, size, z = C_PASSIVE, 4, 3
            ax.scatter(x, g + rng.uniform(-0.3, 0.3), s=size, color=color, lw=0, alpha=0.85 if z > 3 else 0.5,
                       zorder=z)
    ax.axvspan(1.2e-7, 7e-7, color="#f1f0ec", zorder=0, lw=0)
    ax.text(3e-7, -0.72, "=", fontsize=5.6, color=INK2, ha="center", va="bottom")
    for g in range(len(GROUPS)):
        ax.text(3e3, g, f"{counts[g, 1]}/{counts[g, 0]}", fontsize=5.6, color=INK, va="center", ha="left")
    ax.text(3e3, -0.75, "changed", fontsize=5.2, color=INK2, ha="left", va="bottom")
    ax.set_xscale("log")
    ax.set_xlim(1.2e-7, 1e3)
    ax.set_xticks([1e-5, 1e-2, 1e1])
    ax.set_ylim(len(GROUPS) - 0.45, -0.75)
    ax.set_yticks(range(len(GROUPS)))
    ax.set_yticklabels([g for g, _ in GROUPS], fontsize=5.8)
    ax.set_xlabel(r"|observed $-$ $S_0$| / $S_0$")
    ax.tick_params(axis="y", length=0)
    ax.spines["left"].set_visible(False)
    ax.grid(True, axis="x", lw=0.3, color="#e6e5e0", zorder=0)
    ax.legend(handles=[Line2D([], [], ls="", marker="o", ms=3.4, color=c) for c in (C_V2, C_V3, C_PASSIVE)],
              labels=["factor site, v2 only", "factor site, v2 and v3", "other read"], loc="lower center",
              bbox_to_anchor=(0.42, 1.0), ncol=1, frameon=False, fontsize=5.4, handletextpad=0.2,
              borderaxespad=0.1, labelspacing=0.15)
    fig.savefig(out / "fig5a.pdf")
    plt.close(fig)


def panel_b(out: Path, cases, f2, summary) -> None:
    final = {r["case"]: r for r in summary["rows"]}
    order = sorted(cases, key=lambda n: (0 if f2.get(n) else 1, -len(cases[n].get("entry_frames") or [])))
    fig, ax = plt.subplots(figsize=(1.55, 1.95))
    for y, name in enumerate(order):
        d = cases[name]
        frames = d.get("entry_frames") or []
        reads = d.get("scoped_reads") or []
        seqs = [e.get("exit_seq", 0) for e in frames] + [r.get("seq", 0) for r in reads]
        top = max(seqs) if seqs else 1
        ax.plot([0, 1], [y, y], color="#e6e5e0", lw=0.6, zorder=1)
        for e in frames:
            a, b = e.get("enter_seq", 0) / top, e.get("exit_seq", 0) / top
            if e.get("is_harm_frame"):
                ax.add_patch(Rectangle((a, y - 0.32), max(b - a, 0.004), 0.64, color=C_VICTIM, lw=0, alpha=0.55,
                                       zorder=2))
            else:
                ax.plot([a, a], [y - 0.18, y + 0.18], color=MUTED, lw=0.3, zorder=2)
        for r in reads:
            v0, ve = word(r.get("v0_value")), word(r.get("observed_value"))
            if v0 is not None and ve is not None and v0 != ve:
                ax.plot(r.get("seq", 0) / top, y, marker="|", ms=4.2, mew=0.9, color=C_NEAR, zorder=3)
        row = final.get(name, {})
        fin = str(row.get("final", ""))
        tag = "SB" if "CAUSE" in fin else ("T" if "third_party" in fin else
                                             ("nf" if "no_harm_frame" in str(row.get("final_reason", "")) + fin else "–"))
        ax.text(1.03, y, tag, fontsize=5.2, color=INK2, va="center", ha="left")
    ax.set_yticks(range(len(order)))
    ax.set_yticklabels([short(n) for n in order], fontsize=5.0)
    ax.set_ylim(len(order) - 0.5, -0.5)
    ax.set_xlim(0, 1)
    ax.set_xticks([0, 0.5, 1])
    ax.set_xlabel("Normalized execution order")
    ax.tick_params(axis="y", length=0)
    ax.spines["left"].set_visible(False)
    n7 = sum(1 for n in order if f2.get(n))
    ax.axhline(n7 - 0.5, color=INK2, lw=0.4, ls=(0, (2, 2)))
    ax.legend(handles=[Rectangle((0, 0), 1, 1, color=C_VICTIM, alpha=0.55),
                       Line2D([], [], color=MUTED, lw=0.6),
                       Line2D([], [], ls="", marker="|", ms=4, mew=0.9, color=C_NEAR)],
              labels=["harm frame", "other victim frame", "changed read"], loc="lower center",
              bbox_to_anchor=(0.45, 1.0), ncol=2, frameon=False, fontsize=5.2, handlelength=1.0,
              columnspacing=0.5, handletextpad=0.3, borderaxespad=0.1)
    fig.savefig(out / "fig5b.pdf")
    plt.close(fig)


def panel_c(out: Path, summary) -> None:
    rows = [r for r in summary["rows"] if r.get("factor") not in (None, "-", "", [])]

    def cls(rec):
        if not isinstance(rec, dict):
            return "none"
        if "third_party" in str(rec.get("reason")) or rec.get("origin") == "third_party":
            return "third_party"
        return "victim" if rec.get("origin") == "victim" or rec.get("verdict") == "CAUSE_BLOCKED" else "none"

    modes = ["unscoped", "scoped_whole_tx", "frame_local"]
    labels = ["unscoped", "read-\nscoped", "frame-\nlocal"]
    order = ["victim", "third_party"]
    colors = {"victim": C_VICTIM, "third_party": C_THIRD}
    seqs = [[cls(r.get(m)) for m in modes] for r in rows]
    fig, ax = plt.subplots(figsize=(0.95, 1.95))
    xs = [0, 1, 2]
    w = 0.16
    # stack positions per column
    pos = []
    for j in range(3):
        col = {}
        y = 0.0
        for o in order:
            members = [i for i, s in enumerate(seqs) if s[j] == o]
            members.sort(key=lambda i: (order.index(seqs[i][max(j - 1, 0)]), i))
            for i in members:
                col[i] = y
                y += 1
            y += 0.4
        pos.append(col)
    for i, s in enumerate(seqs):
        for j in range(2):
            y0, y1 = pos[j][i], pos[j + 1][i]
            t = np.linspace(0, 1, 30)
            ease = t * t * (3 - 2 * t)
            yc = y0 + (y1 - y0) * ease
            xc = xs[j] + w + (xs[j + 1] - xs[j] - 2 * w) * t
            col = colors[s[j + 1]] if s[j] != s[j + 1] else colors[s[j]]
            ax.add_patch(Polygon(np.c_[np.r_[xc, xc[::-1]], np.r_[yc + 0.08, yc[::-1] + 0.92]], closed=True,
                                 color=col, alpha=0.28, lw=0, zorder=1))
        for j in range(3):
            ax.add_patch(Rectangle((xs[j] - w, pos[j][i] + 0.08), 2 * w, 0.84, color=colors[s[j]], lw=0, zorder=2))
    ax.set_xlim(-0.35, 2.35)
    ax.set_ylim(len(rows) + 0.6, -0.2)
    ax.set_xticks(xs)
    ax.set_xticklabels(labels, fontsize=5.6)
    ax.set_yticks([])
    for sname in ("left", "right", "top"):
        ax.spines[sname].set_visible(False)
    ax.legend(handles=[Rectangle((0, 0), 1, 1, color=colors[o]) for o in order] +
              [Rectangle((0, 0), 1, 1, color=INK)],
              labels=["victim", "third party", "attacker (0)"], loc="lower center", bbox_to_anchor=(0.5, 1.0),
              ncol=1, frameon=False, fontsize=5.4, handlelength=0.9, handletextpad=0.3, borderaxespad=0.1,
              labelspacing=0.15)
    ax.set_xlabel("Revert origin")
    fig.savefig(out / "fig5c.pdf")
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--discover", type=Path, default=ROOT / ".cache" / "rq3_discover")
    ap.add_argument("--summary", type=Path, default=ROOT / ".cache" / "rq3_final_v2" / "summary.json")
    ap.add_argument("--factors-v2", type=Path, default=ROOT / "eval" / "rq3" / "fixed20_factors.json")
    ap.add_argument("--factors-v3", type=Path, default=ROOT / "eval" / "rq3" / "fixed20_factors_v3.json")
    ap.add_argument("--out", type=Path, default=ROOT / "paper" / "figures")
    args = ap.parse_args()
    style()
    cases = load(args.discover)
    f2, f3 = factor_sites(args.factors_v2), factor_sites(args.factors_v3)
    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    args.out.mkdir(parents=True, exist_ok=True)
    panel_a(args.out, cases, f2, f3)
    panel_b(args.out, cases, f2, summary)
    panel_c(args.out, summary)
    print("wrote", *(args.out / f"fig5{p}.pdf" for p in "abc"))


if __name__ == "__main__":
    main()
