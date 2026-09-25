"""Fig. 3 (RQ1): screening under shape ambiguity, drawn as three separate panels.

    python -m eval.plots.fig_rq1 --out paper/figures

Reads the frozen Stage-1 artifacts (local only, git-ignored):
  eval/results/runs/p7-screening-model-corrected-20260912-r2/  grouped-v2 test predictions and threshold
  eval/results/runs/p7-near-negative-20260912-r1/              ordinary / near-negative cohorts of that test set
  eval/results/runs/p7-robustness-20260912-r1/                 temporal and held-family grouped folds
  eval/results/e1_evaluation.json + e1_trace_cache.jsonl       stratified split (block leakage), shown for contrast

Writes fig3a.pdf (PR curves), fig3b.pdf (score distributions), fig3c.pdf (AUPRC across evaluations).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
RES = ROOT / "eval" / "results"
RUNS = RES / "runs"

# Validated categorical slots 1-3 (all-pairs CVD safe); ink colours for text and neutral series.
C_ATTACK = "#2a78d6"
C_NEAR = "#eb6834"
C_ORD = "#1baf7a"
INK = "#0b0b0b"
INK2 = "#52514e"
MUTED = "#9a9892"

PANEL_W, PANEL_H = 1.62, 1.55  # inches; three panels fit LNCS \textwidth (12.2 cm)


def style() -> None:
    plt.rcParams.update({
        "font.family": "serif",
        "font.serif": ["cmr10", "Computer Modern Roman", "DejaVu Serif"],
        "mathtext.fontset": "cm",
        "axes.formatter.use_mathtext": True,
        "axes.unicode_minus": False,
        "font.size": 7,
        "axes.labelsize": 7,
        "axes.titlesize": 7,
        "xtick.labelsize": 6.5,
        "ytick.labelsize": 6.5,
        "legend.fontsize": 6,
        "axes.edgecolor": INK2,
        "axes.linewidth": 0.5,
        "xtick.color": INK2,
        "ytick.color": INK2,
        "xtick.major.width": 0.5,
        "ytick.major.width": 0.5,
        "xtick.major.size": 2,
        "ytick.major.size": 2,
        "axes.labelcolor": INK,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "pdf.fonttype": 42,
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.02,
    })


def load_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def pr_curve(labels: np.ndarray, scores: np.ndarray):
    """Step PR curve (recall, precision) and average precision, as in sklearn."""
    order = np.argsort(-scores, kind="mergesort")
    y, s = labels[order], scores[order]
    distinct = np.r_[np.where(np.diff(s))[0], y.size - 1]
    tp = np.cumsum(y)[distinct]
    fp = (1 + distinct) - tp
    precision = tp / (tp + fp)
    recall = tp / y.sum()
    ap = float(np.sum(np.diff(np.r_[0.0, recall]) * precision))
    return np.r_[0.0, recall], np.r_[1.0, precision], ap


def operating_point(labels, scores, tau):
    pred = scores >= tau
    tp = int((pred & (labels == 1)).sum())
    fp = int((pred & (labels == 0)).sum())
    return tp / labels.sum(), (tp / (tp + fp) if tp + fp else 1.0), tp, fp


def grouped_test():
    preds = load_json(RUNS / "p7-screening-model-corrected-20260912-r2" / "test_predictions.json")
    tau = load_json(RUNS / "p7-screening-model-corrected-20260912-r2" / "metrics.json")["thresholds"]
    paired = load_json(RUNS / "p7-near-negative-20260912-r1" / "paired_metrics.json")
    near = set(paired["near_negative"]["hashes"])
    ordinary = set(paired["ordinary"]["hashes"])
    rows = [(p["tx_hash"], int(p["label"]), float(p["score"])) for p in preds]
    return rows, near, ordinary, float(tau["0.01"]), float(tau["0.001"])


def stratified_test():
    ev = load_json(RES / "e1_evaluation.json")
    attack = set()
    with open(RES / "e1_trace_cache.jsonl", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r.get("label") == "attack":
                attack.add(r["tx_hash"])
    rows = [(h, int(h in attack), float(s)) for h, s in ev["scores_test"].items()]
    return rows, float(ev["operating_thresholds"]["0.01"])


def panel_a(out: Path, g, s) -> None:
    rows, near, ordinary, tau, _ = g
    grouped = load_json(RUNS / "p7-screening-model-corrected-20260912-r2" / "metrics.json")["metrics"]
    paired = load_json(RUNS / "p7-near-negative-20260912-r1" / "paired_metrics.json")
    strat = load_json(RES / "e1_evaluation.json")["metrics"]
    fig, ax = plt.subplots(figsize=(1.42, 1.12))
    lab = np.array([r[1] for r in rows])
    sc = np.array([r[2] for r in rows])
    is_ord = np.array([r[0] in ordinary for r in rows])
    srows, stau = s
    sl = np.array([r[1] for r in srows])
    ss = np.array([r[2] for r in srows])
    curves = [
        # (label, labels, scores, tau, colour, linestyle, reported AUPRC)
        ("stratified (leaky)", sl, ss, stau, MUTED, (0, (2.5, 1.5)), strat["auc_pr"]),
        ("grouped, all bg.", lab, sc, tau, INK, "-", grouped["auc_pr"]),
        ("grouped, ordinary bg.", lab[(lab == 1) | is_ord], sc[(lab == 1) | is_ord], tau, C_ORD, "-",
         paired["ordinary"]["metrics"]["auc_pr"]),
    ]
    for name, y, x, t_, color, ls, auprc in curves:
        r, p, _ = pr_curve(y, x)
        ax.step(r, p, where="post", color=color, lw=1.0, ls=ls, zorder=3,
                label=f"{name} ({auprc:.3f})")
        rr, pp, _, _ = operating_point(y, x, t_)
        ax.plot(rr, pp, "o", ms=3.4, mfc=color, mec="white", mew=0.6, zorder=4)
    ax.set_xlim(0, 1.0)
    ax.set_ylim(0, 1.04)
    ax.set_xlabel("Recall")
    ax.set_ylabel("Precision", labelpad=1)
    ax.set_xticks([0, 0.5, 1])
    ax.set_yticks([0, 0.5, 1])
    ax.grid(True, lw=0.3, color="#e6e5e0", zorder=0)
    ax.legend(loc="lower left", bbox_to_anchor=(-0.02, 1.0), frameon=False, handlelength=1.8,
              borderaxespad=0.0, labelspacing=0.2, fontsize=5.6)
    fig.savefig(out / "fig3a.pdf")
    plt.close(fig)


def panel_b(out: Path, g) -> None:
    rows, near, ordinary, tau, tau01 = g
    groups = [
        ("attacks", [r[2] for r in rows if r[1] == 1], C_ATTACK),
        ("near-neg.", [r[2] for r in rows if r[1] == 0 and r[0] in near], C_NEAR),
        ("ordinary", [r[2] for r in rows if r[1] == 0 and r[0] in ordinary], C_ORD),
    ]
    fig, ax = plt.subplots(figsize=(1.30, 1.42))
    rng = np.random.default_rng(7)
    for i, (name, vals, color) in enumerate(groups):
        v = np.clip(np.array(vals), 1e-4, 1.0)
        y = i + rng.uniform(-0.28, 0.28, v.size)
        ax.scatter(v, y, s=5, color=color, alpha=0.55, lw=0, zorder=3)
        q1, med, q3 = np.quantile(v, [0.25, 0.5, 0.75])
        ax.plot([q1, q3], [i, i], color=INK, lw=1.4, zorder=4, solid_capstyle="butt")
        ax.plot(med, i, "|", color="white", ms=5, mew=1.2, zorder=5)
        hit = int((v >= tau).sum())
        ax.text(1.35, i, f"{hit}/{v.size}", fontsize=5.8, color=INK, va="center", ha="left")
    ax.axvline(tau, color=INK, lw=0.7, ls="--", zorder=2)
    ax.axvline(tau01, color=INK2, lw=0.5, ls=":", zorder=2)
    ax.text(tau, 2.45, r"$\tau_{1\%}$", fontsize=5.6, ha="right", va="bottom", rotation=90, color=INK)
    ax.text(tau01, 2.45, r"$\tau_{0.1\%}$", fontsize=5.6, ha="right", va="bottom", rotation=90, color=INK2)
    ax.text(1.35, -0.62, "alerts", fontsize=5.6, ha="left", va="bottom", color=INK2)
    ax.set_xscale("log")
    ax.set_xlim(1e-4, 1.0)
    ax.set_xticks([1e-4, 1e-2, 1])
    ax.set_ylim(-0.6, 2.5)
    ax.set_yticks(range(len(groups)))
    ax.set_yticklabels([gname for gname, _, _ in groups])
    ax.invert_yaxis()
    ax.set_xlabel("Calibrated score")
    ax.tick_params(axis="y", length=0)
    ax.spines["left"].set_visible(False)
    ax.grid(True, axis="x", lw=0.3, color="#e6e5e0", zorder=0)
    fig.savefig(out / "fig3b.pdf")
    plt.close(fig)


def panel_c(out: Path, g, s) -> None:
    rows, near, ordinary, _, _ = g
    grouped = load_json(RUNS / "p7-screening-model-corrected-20260912-r2" / "metrics.json")
    paired = load_json(RUNS / "p7-near-negative-20260912-r1" / "paired_metrics.json")
    rob = load_json(RUNS / "p7-robustness-20260912-r1" / "grouped_robustness.json")["results"]
    strat = load_json(RES / "e1_evaluation.json")

    def entry(name, m, n_att, n_neg):
        m1 = m["0.01"]
        return dict(name=name, auprc=m["auc_pr"], fpr=m1["realized_fpr"], n_att=n_att,
                    prev=n_att / (n_att + n_neg))

    items = [
        entry("stratified (leaky)", strat["metrics"], strat["n_test_attack"], strat["n_test_benign"]),
        entry("grouped split", grouped["metrics"], 16, 676),
        entry("ordinary bg. only", paired["ordinary"]["metrics"], 16, paired["ordinary"]["n_negative"]),
        entry("near-neg. only", paired["near_negative"]["metrics"], 16, paired["near_negative"]["n_negative"]),
    ]
    fam_label = {"accounting": "accounting", "governance/access": "governance", "oracle": "oracle",
                 "token": "token logic", "flash-loan": "flash loan", "precision": "precision",
                 "rug-pull": "rug pull", "bridge": "bridge"}
    for r in rob:
        m = r["metrics"]
        m1 = m["0.01"]
        n_att = round(m1["tp"] / m1["recall"]) if m1["recall"] else None
        if r["experiment"].startswith("E1-temporal"):
            n_att = 16
            items.append(entry("temporal holdout", m, n_att, r["n_test"] - n_att))
    fams = []
    for r in rob:
        if not r["experiment"].startswith("E2-held-family"):
            continue
        m = r["metrics"]
        m1 = m["0.01"]
        n_att = {"accounting": 25, "governance/access": 26, "oracle": 12, "token": 7, "flash-loan": 4,
                 "precision": 3, "rug-pull": 2, "bridge": 1}[r["held_family"]]
        fams.append(entry(fam_label[r["held_family"]], m, n_att, r["n_test"] - n_att))
    fams.sort(key=lambda e: -e["n_att"])
    items += [None] + fams  # None = "held-out family:" header row

    fig, ax = plt.subplots(figsize=(1.18, 1.42))
    y = np.arange(len(items))
    for yi, e in zip(y, items):
        if e is None:
            continue
        within = e["fpr"] <= 0.01
        size = 6 + 1.6 * e["n_att"]
        ax.plot([e["prev"], e["auprc"]], [yi, yi], color="#d8d6cf", lw=0.8, zorder=1)
        ax.plot(e["prev"], yi, "|", color=MUTED, ms=4, mew=0.8, zorder=2)
        color = MUTED if e["name"].startswith("stratified") else C_ATTACK
        ax.scatter(e["auprc"], yi, s=size, facecolor=color if within else "white",
                   edgecolor=color, lw=0.9, zorder=3)
    ax.set_yticks(y)
    ticks = ax.set_yticklabels([("held-out family:" if e is None else e["name"]) for e in items], fontsize=5.4)
    for tick, e in zip(ticks, items):
        if e is None:
            tick.set_fontstyle("italic")
            tick.set_color(INK2)
    ax.invert_yaxis()
    ax.set_xlim(0, 1.0)
    ax.set_xticks([0, 0.5, 1])
    ax.set_xlabel("AUPRC")
    ax.tick_params(axis="y", length=0)
    ax.spines["left"].set_visible(False)
    ax.grid(True, axis="x", lw=0.3, color="#e6e5e0", zorder=0)
    ax.axhline(3.5, color="#e6e5e0", lw=0.5)
    ax.axhline(4.5, color="#e6e5e0", lw=0.5)
    fig.savefig(out / "fig3c.pdf")
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "paper" / "figures")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    style()
    g = grouped_test()
    s = stratified_test()
    panel_a(args.out, g, s)
    panel_b(args.out, g)
    panel_c(args.out, g, s)
    print("wrote", *(args.out / f"fig3{p}.pdf" for p in "abc"))


if __name__ == "__main__":
    main()
