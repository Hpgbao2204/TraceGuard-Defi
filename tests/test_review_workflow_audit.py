import json

from corpus.scripts.audit_review_workflow import (
    _packet_identity_errors, audit_e4_files,
)


def test_missing_adjudication_is_reported_as_not_supplied(tmp_path):
    fixed = tmp_path / "fixed.json"
    fixed.write_text(json.dumps({"cases": [
        {"case_id": "case", "tx_hash": "0x1"},
    ]}))
    result = audit_e4_files(
        tmp_path / "reviewer_a.jsonl",
        tmp_path / "reviewer_b.jsonl",
        fixed,
        tmp_path / "adjudicated.jsonl",
    )
    assert result["final_sidecar"] == {
        "present": False, "valid": False, "errors": ["not_supplied"]
    }


def test_packet_identity_rejects_wrong_packet_hash():
    row = {
        "packet_schema_version": 1,
        "fixed_set_sha256": "a" * 64,
        "packet_sha256": "b" * 64,
    }
    manifest = {"packet_hashes": {"e4_reviewer_a": "c" * 64}}
    errors = _packet_identity_errors([row], "e4_reviewer_a", "a" * 64, manifest)
    assert errors == ["packet_sha256_mismatch"]


def test_packet_identity_rejects_missing_metadata():
    errors = _packet_identity_errors(
        [{"packet_schema_version": 1}], "e4_reviewer_a", "a" * 64, {})
    assert errors == ["fixed_set_sha256_mismatch", "packet_sha256_missing"]
