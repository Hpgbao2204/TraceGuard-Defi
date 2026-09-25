"""Offline validation/materialization audit for supplementary Reviewer-C output."""
from __future__ import annotations
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "corpus/annotations/review_bundles_supplementary/m6_supplementary_adjudication_reviewer_c_v2.jsonl"
OUT = ROOT / "eval/results/m6_supplementary_reviewer_c_audit.json"

def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()

def parse_json_field(value):
    if isinstance(value, (list, dict)):
        return value
    if isinstance(value, str) and value.strip():
        try: return json.loads(value)
        except json.JSONDecodeError: return None
    return None

def audit():
    rows = [json.loads(line) for line in SRC.read_text().splitlines() if line.strip()]
    result_rows = []
    for row in rows:
        entities = parse_json_field(row.get("protected_entities"))
        assets = parse_json_field(row.get("harm_assets"))
        errors = []
        if not isinstance(entities, list) or not entities:
            errors.append("missing_or_invalid_protected_entities")
        if not isinstance(assets, list) or not assets:
            errors.append("missing_or_invalid_harm_assets")
        lmin = row.get("lmin_usd")
        try:
            if lmin in (None, "") or float(lmin) < 0: errors.append("missing_or_invalid_lmin_usd")
        except (TypeError, ValueError): errors.append("missing_or_invalid_lmin_usd")
        if not str(row.get("valuation_source") or "").strip():
            errors.append("missing_valuation_source")
        factors = row.get("root_cause_gt") or []
        if not isinstance(factors, list):
            factors = [x.strip() for x in str(factors).split(",") if x.strip()]
        subtype = row.get("oracle_subtype") or None
        release = (("f_fl" in factors and row.get("flash_loan_role") == "causal") or
                   ("f_orc" in factors and subtype == "external_feed"))
        result_rows.append({"case_id": row["case_id"], "tx_hash": row["tx_hash"],
                            "root_cause": factors, "oracle_subtype": subtype,
                            "release_operator_supported": release,
                            "harm_status": "MEASURABLE" if not errors else "UNMEASURABLE",
                            "errors": errors, "normalized_protected_entities": entities,
                            "normalized_harm_assets": assets})
    result = {"schema_version": 1, "source_sha256": sha256(SRC),
              "record_count": len(result_rows), "cases": result_rows,
              "measurable_count": sum(r["harm_status"] == "MEASURABLE" for r in result_rows),
              "release_operator_supported_count": sum(r["release_operator_supported"] for r in result_rows),
              "causal_eligible_count": sum(r["harm_status"] == "MEASURABLE" and r["release_operator_supported"] for r in result_rows),
              "status": "READY_FOR_SEPARATE_FREEZE" if any(r["harm_status"] == "MEASURABLE" and r["release_operator_supported"] for r in result_rows) else "NO_CASE_READY_FOR_FREEZE"}
    OUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result

if __name__ == "__main__":
    r = audit()
    print(json.dumps({k: r[k] for k in ("record_count", "measurable_count", "release_operator_supported_count", "causal_eligible_count", "status")}, indent=2))
