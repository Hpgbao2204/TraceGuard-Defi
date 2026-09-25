"""Build the E5 Phase-0 claim crosswalk from frozen local artifacts.

This module is deliberately conservative: one corpus is one source.  Missing
external sources remain missing and are never copied or inferred as agreement.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "docs/m4_frozen_case_manifest.json"
INCIDENTS = ROOT / "corpus/incidents.jsonl"
OUT = ROOT / "eval/results/e5_rcfh/label_crosswalk.json"
EXTERNAL = ROOT / "eval/results/e5_rcfh/incident_explorer_matches.json"
RESOLVER_VERSION = "e5-phase0-crosswalk-v1"

SOURCE_NAMES = ("defihacklabs_local_corpus", "incident_explorer", "rca_repo", "txray", "lookahead", "bastet")
EXACT_MATCHES = {"EXACT", "EXACT_TX_HASH", "CASE_ID_ONLY"}


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_fixed_manifest(path: Path = MANIFEST) -> dict[str, Any]:
    return json.loads(path.read_text())


def load_incidents(path: Path = INCIDENTS) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _norm_hash(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip().lower()
    return value if re.fullmatch(r"0x[0-9a-f]{64}", value) else None


def _parse_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def resolve_incident(case: dict[str, Any], records: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, str]:
    case_id = case["case_id"]
    tx_hash = _norm_hash(case.get("tx_hash"))
    exact = [r for r in records if r.get("id") == case_id]
    exact_hash = [r for r in exact if tx_hash and tx_hash in {_norm_hash(h) for h in r.get("tx_hashes", [])}]
    if len(exact_hash) == 1:
        return exact_hash[0], "EXACT"
    if len(exact) == 1:
        return exact[0], "CASE_ID_ONLY"

    # Fallback is intentionally marked fuzzy and is not silently merged into
    # exact agreement metrics.
    prefix = case_id.removeprefix("defihacklabs-")
    parts = prefix.rsplit("-", 3)
    protocol = parts[0] if len(parts) == 4 else prefix
    target_date = _parse_date(case_id[-10:])
    candidates = []
    for r in records:
        if str(r.get("protocol", "")).lower().replace(" ", "") != protocol.lower().replace(" ", ""):
            continue
        rd = _parse_date(r.get("date"))
        if target_date and rd and abs((rd - target_date).days) <= 3:
            candidates.append(r)
    return (candidates[0], "FUZZY") if len(candidates) == 1 else (None, "MISSING")


def _claim(record: dict[str, Any]) -> dict[str, Any]:
    factors = record.get("gt_factors") or []
    return {
        "factor_labels": factors,
        "attack_type": record.get("attack_type"),
        "narrative": record.get("notes"),
        "label_type": "claim",
    }


def candidate_sok_groups(record: dict[str, Any] | None) -> list[str]:
    if not record:
        return []
    text = " ".join(str(x) for x in [record.get("attack_type"), record.get("notes"), *(record.get("gt_factors") or [])]).lower()
    groups: list[str] = []
    if "oracle" in text or "price" in text or "reserve" in text or "exchange-rate" in text:
        groups.append("oracle-and-price-manipulation-attacks")
    if "flash" in text or "f_fl" in text:
        groups.append("flash-loan-attacks")
    if "reentr" in text:
        groups.append("reentrancy")
    if "auth" in text or "approval" in text or "signature" in text or "access" in text:
        groups.append("access-control-and-authorization")
    if "round" in text or "precision" in text or "account" in text or "exchange rate" in text:
        groups.append("arithmetic-and-accounting")
    if not groups and record.get("attack_type"):
        groups.append("UNRESOLVED_CANDIDATE_FROM_LOCAL_CLAIM")
    return sorted(set(groups))


def _missing_source() -> dict[str, Any]:
    return {"claim": None, "match_confidence": "MISSING", "label_type": None}


def _external_claim(record: dict[str, Any]) -> dict[str, Any]:
    return {"claim_type": record.get("claim_type"), "narrative": record.get("root_cause"), "label_type": "independent_claim"}


def _label_key(payload: dict[str, Any]) -> tuple[str, ...] | None:
    """Return a conservative comparable label, without treating it as truth."""
    claim = payload.get("claim") or {}
    factors = claim.get("factor_labels") or []
    if factors:
        return tuple(sorted(str(x).strip().lower() for x in factors))
    claim_type = claim.get("claim_type")
    if claim_type:
        return ("claim_type:" + re.sub(r"\\s+", "_", str(claim_type).strip().lower()),)
    return None


def _agreement(rows: list[dict[str, Any]]) -> dict[str, Any]:
    pairs: dict[str, dict[str, int]] = defaultdict(lambda: {"n": 0, "agree": 0})
    for row in rows:
        available = []
        for source, payload in row["sources"].items():
            if payload.get("claim") is not None and payload.get("match_confidence") in EXACT_MATCHES:
                label = _label_key(payload)
                if label is not None:
                    available.append((source, label))
        for i, (a, av) in enumerate(available):
            for b, bv in available[i + 1 :]:
                key = "|".join(sorted((a, b)))
                pairs[key]["n"] += 1
                pairs[key]["agree"] += int(av == bv)
    return {k: {**v, "agreement": (v["agree"] / v["n"] if v["n"] else None), "cohen_kappa": None} for k, v in pairs.items()}


def build_crosswalk(manifest: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    external = {}
    if EXTERNAL.exists():
        ext = json.loads(EXTERNAL.read_text())
        external = {x["case_id"]: x for x in ext.get("matches", [])}
    cases = []
    for frozen in manifest["cases"]:
        record, confidence = resolve_incident(frozen, records)
        sources = {name: _missing_source() for name in SOURCE_NAMES}
        if record:
            sources["defihacklabs_local_corpus"] = {
                "claim": _claim(record),
                "match_confidence": confidence,
                "source_record_id": record.get("id"),
                "source_url": record.get("source_url"),
            }
        if frozen["case_id"] in external:
            ext = external[frozen["case_id"]]
            sources["incident_explorer"] = {"claim": _external_claim(ext), "match_confidence": ext["match_confidence"], "source_url": ext.get("source_url", "https://github.com/SunWeb3Sec/DeFiHackLabs-Incident-Explorer")}
        cases.append({
            "case_id": frozen["case_id"],
            "tx_hash": frozen.get("tx_hash"),
            "sources": sources,
            "sok_cause_group_candidates": candidate_sok_groups(record),
            "sok_mapping_status": "CANDIDATE_ONLY_NOT_GROUND_TRUTH",
        })

    exact_source_counts = [sum(p.get("claim") is not None and p.get("match_confidence") in EXACT_MATCHES for p in c["sources"].values()) for c in cases]
    return {
        "schema_version": 1,
        "artifact": "e5-label-crosswalk",
        "resolver_version": RESOLVER_VERSION,
        "corpus_id": "m4-frozen-20",
        "corpus_case_count": len(cases),
        "corpus_case_ids_sha256": _sha256_bytes("\n".join(sorted(c["case_id"] for c in cases)).encode()),
        "input_manifest_sha256": _sha256_bytes(MANIFEST.read_bytes()),
        "input_incidents_sha256": _sha256_bytes(INCIDENTS.read_bytes()),
        "source_policy": "one local corpus is one source; missing external sources remain missing",
        "cases": cases,
        "agreement": _agreement(cases),
        "gate0": {
            "all_cases_have_at_least_one_source": all(n >= 1 for n in exact_source_counts),
            "cases_with_at_least_two_sources": sum(n >= 2 for n in exact_source_counts),
            "minimum_two_source_cases": 5,
            "status": "PARTIAL" if all(n >= 1 for n in exact_source_counts) else "FAIL",
            "local_claim_coverage": f"{sum(n >= 1 for n in exact_source_counts)}/{len(cases)}",
            "independent_source_coverage": f"{sum(n >= 2 for n in exact_source_counts)}/{len(cases)}",
            "cross_source_agreement": "ESTIMABLE_ON_EXACT_OVERLAPS" if sum(n >= 2 for n in exact_source_counts) else "NOT_ESTIMABLE",
            "limitation": "Agreement compares conservative raw labels only; semantic equivalence still requires reviewed normalization. Missing sources remain missing.",
        },
    }


def main() -> None:
    result = build_crosswalk(load_fixed_manifest(), load_incidents())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(OUT), "case_count": len(result["cases"]), "gate0": result["gate0"]}, indent=2))


if __name__ == "__main__":
    main()
