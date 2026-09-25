"""Aggregate per-mode simulation records into the M3 metrics."""
from __future__ import annotations

import math
from collections import Counter, defaultdict

SLOT_BUDGET_MS = 12_000.0
TIGHT_BUDGET_MS = 500.0


def wilson(k: int, n: int, z: float = 1.96) -> list[float] | None:
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0.0, c - h), 4), round(min(1.0, c + h), 4)]


def rate(k: int, n: int) -> dict:
    return {"k": k, "n": n, "rate": round(k / n, 4) if n else None, "wilson95": wilson(k, n)}


def pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    i = min(len(s) - 1, max(0, math.ceil(q * len(s)) - 1))
    return round(s[i], 3)


def summarize(slots: list[dict], harm_none_a: float | None = None) -> dict:
    bundles = [b for s in slots for b in s["bundles"]]
    decided = [b for b in bundles if b["status"] in ("included", "excluded")]
    sand = [b for b in decided if b["attack"]]
    benign = [b for b in decided if not b["attack"]]

    by_variant = defaultdict(list)
    for b in sand:
        by_variant[b["variant"]].append(b)
    by_kind = defaultdict(list)
    for b in benign:
        by_kind[b["kind"]].append(b)

    landed = [b for b in bundles if b["attack"] and b["status"] == "included"]
    harm_a = sum(b["gt_harm_a"] or 0.0 for b in landed)
    l2_checked = [b for b in bundles if b["attack"] and b["verdict"] in ("CAUSE", "NO_EFFECT")]
    l2_match = sum(b["harm_l2"] == b["gt_harm"] for b in l2_checked if b["gt_harm"] is not None)
    l2_checked_gt = [b for b in l2_checked if b["gt_harm"] is not None]

    per_slot = [s["l1_ms"] + s["l2_ms"] for s in slots]
    l2_bundle = [b["l2_ms"] for b in bundles if b["verdict"]]
    verdicts = Counter((b["verdict"], b["confound_kind"] or b["reason"] or "") for b in bundles if b["verdict"])

    def by_decision(group: list[dict]) -> dict:
        """Layer-2 policy outputs: EXCLUDE on CAUSE, and DEFAULT with how the builder resolved it."""
        return {"exclude_on_cause": rate(sum(b["decision"] == "EXCLUDE" for b in group), len(group)),
                "default": rate(sum(b["decision"] == "DEFAULT" for b in group), len(group)),
                "default_then_excluded": sum(b["decision"] == "DEFAULT" and b["status"] == "excluded"
                                             for b in group)}

    out = {
        "slots": len(slots),
        "users": sum(s["n_users"] for s in slots),
        "user_txs_reverted": sum(s["users_reverted"] for s in slots),
        "bundles_total": len(bundles),
        "bundles_by_status": dict(Counter(b["status"] for b in bundles)),
        "sandwich_blocked": rate(sum(b["status"] == "excluded" for b in sand), len(sand)),
        "sandwich_blocked_by_variant": {v: rate(sum(b["status"] == "excluded" for b in bs), len(bs))
                                        for v, bs in sorted(by_variant.items())},
        "sandwiches_landed": len(landed),
        "victim_harm_realized_A": round(harm_a, 6),
        "sandwich_decisions": by_decision(sand),
        "benign_decisions": by_decision(benign),
        "benign_blocked": rate(sum(b["status"] == "excluded" for b in benign), len(benign)),
        "benign_blocked_by_kind": {k: rate(sum(b["status"] == "excluded" for b in bs), len(bs))
                                   for k, bs in sorted(by_kind.items())},
        "layer1_flagged": {"sandwich": rate(sum(bool(b["l1_flagged"]) for b in sand), len(sand)),
                           "benign": rate(sum(bool(b["l1_flagged"]) for b in benign), len(benign))},
        "verdicts": {f"{v}{'(' + r + ')' if r else ''}": n for (v, r), n in sorted(verdicts.items())},
        "layer2_harm_equals_ground_truth": {"match": l2_match, "n": len(l2_checked_gt)},
        "latency_ms": {
            "per_slot_filter_p50": pct(per_slot, 0.5),
            "per_slot_filter_p95": pct(per_slot, 0.95),
            "per_slot_filter_max": pct(per_slot, 1.0),
            "per_slot_heuristic_max": pct([s["heuristic_ms"] for s in slots], 1.0),
            "per_bundle_layer1_p95": pct([b["l1_ms"] for b in bundles if b["l1_flagged"] is not None], 0.95),
            "per_bundle_layer2_p50": pct(l2_bundle, 0.5),
            "per_bundle_layer2_p95": pct(l2_bundle, 0.95),
            "slots_within_12s": rate(sum(x <= SLOT_BUDGET_MS for x in per_slot), len(per_slot)),
            "slots_within_500ms": rate(sum(x <= TIGHT_BUDGET_MS for x in per_slot), len(per_slot)),
            "per_slot_build_p50": pct([s["build_ms"] for s in slots], 0.5),
        },
    }
    if harm_none_a is not None:
        avoided = harm_none_a - harm_a
        out["victim_harm_avoided_A"] = round(avoided, 6)
        out["victim_harm_avoided_pct"] = round(100 * avoided / harm_none_a, 2) + 0.0 if harm_none_a else None
    return out


def table(summary: dict) -> str:
    rows = [("mode", "sandw.blocked", "benign blocked", "benign EXCLUDE", "benign DEFAULT", "landed", "harm A",
             "avoided %", "filter ms/slot p95", "L2 ms/bundle p95")]
    for mode, s in summary.items():
        sb, bb, lat = s["sandwich_blocked"], s["benign_blocked"], s["latency_ms"]
        bd = s["benign_decisions"]
        rows.append((mode, f"{sb['k']}/{sb['n']}", f"{bb['k']}/{bb['n']}",
                     f"{bd['exclude_on_cause']['k']}/{bd['exclude_on_cause']['n']}",
                     f"{bd['default']['k']}/{bd['default']['n']}", str(s["sandwiches_landed"]),
                     f"{s['victim_harm_realized_A']:.4f}", str(s.get("victim_harm_avoided_pct", "")),
                     str(lat["per_slot_filter_p95"]), str(lat["per_bundle_layer2_p95"] or "")))
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    lines = ["  ".join(c.ljust(w) for c, w in zip(r, widths)) for r in rows]
    lines.insert(1, "  ".join("-" * w for w in widths))
    return "\n".join(lines)


def breakdown(summary: dict) -> str:
    """Blocked/evaluated per sandwich variant and per benign kind, one column per mode."""
    modes = list(summary)
    keys = sorted({("sandwich", v) for s in summary.values() for v in s["sandwich_blocked_by_variant"]}
                  | {("benign", k) for s in summary.values() for k in s["benign_blocked_by_kind"]})
    rows = [("class", "type", *modes)]
    for cls, key in keys:
        field_ = "sandwich_blocked_by_variant" if cls == "sandwich" else "benign_blocked_by_kind"
        cells = []
        for m in modes:
            r = summary[m][field_].get(key)
            cells.append(f"{r['k']}/{r['n']}" if r else "-")
        rows.append((cls, key, *cells))
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    lines = ["  ".join(c.ljust(w) for c, w in zip(r, widths)) for r in rows]
    lines.insert(1, "  ".join("-" * w for w in widths))
    return "\n".join(lines)
