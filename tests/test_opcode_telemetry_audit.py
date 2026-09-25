from eval.e5.audit_opcode_telemetry import run

def test_current_fixed20_artifacts_do_not_claim_storage_provenance():
    result = run()
    assert result["summary"]["storage_provenance_ready"] == 0
    assert result["summary"]["causal_storage_edges_authorized"] is False
