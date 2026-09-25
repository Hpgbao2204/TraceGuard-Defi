import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _admission():
    return json.loads((ROOT / "eval/results/e5_rcfh/claim_semantic_admission.json").read_text())


def _matrix():
    return json.loads((ROOT / "eval/results/e5_rcfh/claim_testability_matrix.json").read_text())


def test_admission_uses_raw_seam_presence_not_filtered_mapping():
    rows = {x["case_id"]: x for x in _admission()["cases"]}
    assert rows["defihacklabs-erc20transfer-2024-10-22"]["status"] == "RAW_SEAM_MISSING"
    assert rows["defihacklabs-silofinance-2025-06-25"]["raw_seam_group_count"] > 0


def test_exchange_issuance_is_not_matched_by_generic_invariant_label():
    row = next(x for x in _admission()["cases"]
               if x["case_id"] == "defihacklabs-exchangeissuance-index-coop-2026-07-30")
    assert row["status"] == "CLAIM_SEAM_MISMATCH"
    assert row["compatible_operator_types"] == []


def test_mure_signature_seam_requires_review_not_auto_authorization():
    row = next(x for x in _admission()["cases"]
               if x["case_id"] == "defihacklabs-muredistribution-2026-05-21")
    assert row["status"] == "SEMANTIC_REVIEW_REQUIRED"
    assert row["replay_authorized"] is False


def test_target_schema_does_not_treat_hash_or_free_text_as_evm_address():
    matrix = _matrix()
    assert matrix["counts"]["target_effect_defined"] == 1
    assert all(x["target_effect_defined"]["status"] in {
        "PASS", "NOT_TESTABLE_TARGET_SCHEMA"
    } for x in matrix["cases"])
