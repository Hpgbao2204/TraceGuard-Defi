import pytest

from eval.m4_differential import (
    compare_execution_evidence, compare_manifest_evidence, evidence_hash,
    execution_evidence, frozen_case_set_hash, validate_manifest, canonical_logs,
)


def _manifest(count=20):
    import json
    from pathlib import Path
    frozen = json.loads((Path(__file__).parents[1] / "docs/m4_frozen_case_manifest.json").read_text())
    identities = frozen["cases"][:count]
    manifest = {
        "schema_version": 1,
        "source_commit": "abc123",
        "cases": [{
            "case_id": item["case_id"], "tx_hash": item["tx_hash"],
            "block": item["block"], "tx_index": item["tx_index"],
            "context_manifest_hash": "c" * 64,
            "b2_source": "b2-run", "independent_source": "independent-run",
            "independent_engine": "reference-client",
            "independent_version": "1.0",
        } for item in identities],
    }
    manifest["frozen_set_sha256"] = frozen_case_set_hash(manifest["cases"])
    return manifest


def test_m4_manifest_requires_frozen_ten_to_twenty_case_set():
    validate_manifest(_manifest())
    with pytest.raises(ValueError, match="exactly 20"):
        validate_manifest(_manifest(19))


def test_m4_manifest_rejects_non_digest_context_hash():
    manifest = _manifest()
    manifest["cases"][0]["context_manifest_hash"] = "context-0"
    with pytest.raises(ValueError, match="context_manifest_hash"):
        validate_manifest(manifest)


def test_m4_manifest_rejects_wrong_frozen_set_hash():
    manifest = _manifest()
    manifest["frozen_set_sha256"] = "a" * 64
    with pytest.raises(ValueError, match="frozen_set_sha256"):
        validate_manifest(manifest)


def test_m4_manifest_rejects_partial_frozen_set():
    manifest = _manifest(19)
    with pytest.raises(ValueError, match="exactly 20"):
        validate_manifest(manifest)


def test_m4_comparison_passes_only_when_all_required_fields_match():
    evidence = {"status": True, "gas_used": 123, "logs_hash": "a" * 64,
                "relevant_state_hash": "b" * 64}
    result = compare_execution_evidence(evidence, dict(evidence))
    assert result["outcome"] == "PASS"
    assert all(result["comparisons"].values())


def test_m4_comparison_is_inconclusive_on_missing_or_mismatched_evidence():
    left = {"status": True, "gas_used": 123, "logs_hash": "a" * 64,
            "relevant_state_hash": "b" * 64}
    missing = compare_execution_evidence(left, {"status": True})
    assert missing["outcome"] == "INCONCLUSIVE"
    mismatch = compare_execution_evidence(left, {**left, "gas_used": 124})
    assert mismatch["outcome"] == "INCONCLUSIVE"
    assert mismatch["mismatches"] == ["gas_used"]


def test_m4_execution_evidence_hashes_raw_logs_and_relevant_state():
    left = execution_evidence(
        status=True, gas_used=123, logs=[{"address": "0x1"}],
        relevant_post_state={"0x1": {"storage": {"0x2": "0x3"}}},
    )
    right = execution_evidence(
        status=True, gas_used=123, logs=[{"address": "0x1"}],
        relevant_post_state={"0x1": {"storage": {"0x2": "0x3"}}},
    )
    assert compare_execution_evidence(left, right)["outcome"] == "PASS"
    assert evidence_hash({"b": 1, "a": 2}) == evidence_hash({"a": 2, "b": 1})
    incomplete = execution_evidence(status=True, gas_used=123, logs=[])
    assert compare_execution_evidence(left, incomplete)["outcome"] == "INCONCLUSIVE"


def test_canonical_logs_ignores_receipt_metadata_and_preserves_order():
    logs = [{"address": "0xAbC", "topics": ["0xAA"], "data": "0xFf",
             "logIndex": "0x9", "blockNumber": "0x1"}]
    assert canonical_logs(logs) == [{"address": "0xabc", "topics": ["0xaa"], "data": "0xff"}]


def test_m4_comparison_rejects_malformed_equal_values():
    malformed = {"status": True, "gas_used": "123", "logs_hash": "a" * 64,
                 "relevant_state_hash": "b" * 64}
    result = compare_execution_evidence(malformed, dict(malformed))
    assert result["outcome"] == "INCONCLUSIVE"
    assert "invalid execution evidence" in result["reason"]


def test_m4_comparison_rejects_placeholder_digests():
    evidence = {"status": True, "gas_used": 1,
                "logs_hash": "logs", "relevant_state_hash": "state"}
    result = compare_execution_evidence(evidence, dict(evidence))
    assert result["outcome"] == "INCONCLUSIVE"
    assert "invalid execution evidence" in result["reason"]


def test_m4_manifest_rejects_same_producer_for_both_sides():
    manifest = _manifest()
    manifest["cases"][0]["independent_source"] = manifest["cases"][0]["b2_source"]
    with pytest.raises(ValueError, match="independent"):
        validate_manifest(manifest)


def test_m4_manifest_runner_requires_case_provenance_and_compares_all_cases():
    manifest = _manifest()
    evidence = {}
    for case in manifest["cases"]:
        metadata = {
            "source_commit": manifest["source_commit"],
            "case_id": case["case_id"], "tx_hash": case["tx_hash"],
            "block": case["block"], "tx_index": case["tx_index"],
                "context_manifest_hash": case["context_manifest_hash"],
                "acceptance_gate": True,
                "status": True, "gas_used": 123,
            "logs_hash": "a" * 64, "relevant_state_hash": "b" * 64,
        }
        evidence[case["case_id"]] = {
            "b2": dict(metadata, source=case["b2_source"]),
            "independent": dict(
                metadata, source=case["independent_source"],
                engine=case["independent_engine"],
                version=case["independent_version"],
            ),
        }
    result = compare_manifest_evidence(manifest, evidence)
    assert result["outcome"] == "PASS"
    assert result["case_count"] == 20
    assert result["passed_cases"] == 20


def test_m4_manifest_runner_rejects_wrong_source_without_comparing():
    manifest = _manifest()
    case = manifest["cases"][0]
    metadata = {
        "source_commit": "wrong", "case_id": case["case_id"],
        "source": case["b2_source"],
        "tx_hash": case["tx_hash"], "block": case["block"],
        "tx_index": case["tx_index"],
        "context_manifest_hash": case["context_manifest_hash"],
        "status": True, "gas_used": 123, "logs_hash": "a" * 64,
        "relevant_state_hash": "b" * 64,
    }
    evidence = {item["case_id"]: {"b2": dict(metadata, case_id=item["case_id"],
                                             tx_hash=item["tx_hash"], block=item["block"],
                                             tx_index=item["tx_index"],
                                             context_manifest_hash=item["context_manifest_hash"]),
                                  "independent": dict(metadata, source=item["independent_source"],
                                                       engine=item["independent_engine"],
                                                       version=item["independent_version"],
                                                       case_id=item["case_id"],
                                                       tx_hash=item["tx_hash"], block=item["block"],
                                                       tx_index=item["tx_index"],
                                                       context_manifest_hash=item["context_manifest_hash"])}
                for item in manifest["cases"]}
    result = compare_manifest_evidence(manifest, evidence)
    assert result["outcome"] == "INCONCLUSIVE"
    assert all(item["reason"] == "provenance mismatch" for item in result["cases"])


def test_m4_load_and_compare_reads_explicit_json_artifacts(tmp_path):
    import json
    from eval.m4_differential import load_and_compare

    manifest = _manifest()
    evidence = {}
    for case in manifest["cases"]:
        common = {
            "source_commit": manifest["source_commit"],
            "engine": case["independent_engine"],
            "version": case["independent_version"],
            "case_id": case["case_id"], "tx_hash": case["tx_hash"],
            "block": case["block"], "tx_index": case["tx_index"],
                "context_manifest_hash": case["context_manifest_hash"],
                "acceptance_gate": True,
                "status": True, "gas_used": 1,
            "logs_hash": "a" * 64, "relevant_state_hash": "b" * 64,
        }
        evidence[case["case_id"]] = {
            "b2": dict(common, source=case["b2_source"]),
            "independent": dict(common, source=case["independent_source"]),
        }
    manifest_path = tmp_path / "manifest.json"
    evidence_path = tmp_path / "evidence.json"
    manifest_path.write_text(json.dumps(manifest))
    evidence_path.write_text(json.dumps(evidence))
    assert load_and_compare(manifest_path, evidence_path)["outcome"] == "PASS"
