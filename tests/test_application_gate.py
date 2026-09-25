from copy import deepcopy

from eval.e4.application_gate import application_gate
from eval.e4.policy_v2 import apply_policy_rows


def fixture():
    return {"prestate_proof_verified": True, "prefix_gas_match": True,
            "target_index": 2, "mutation_application": [
                {"kind": "code", "address": "0xabc", "before": "0x00",
                 "after": "0x01", "target_index": 2, "prefix_completed": 2}]}


def test_readback_and_application_failures():
    requested = {"target_code": {"0xabc": "0x01"}}
    assert application_gate(fixture(), requested, 2) == (True, "application-verified")
    for field, value in [("address", "0xwrong"), ("after", "0xff"),
                         ("before", "0x01"), ("prefix_completed", 1),
                         ("target_index", 1)]:
        payload = fixture()
        payload["mutation_application"][0][field] = value
        assert not application_gate(payload, requested, 2)[0]
    payload = fixture()
    payload.pop("mutation_application")
    assert not application_gate(payload, requested, 2)[0]


def test_full_storage_override_is_rejected():
    requested = {"state": {"0xabc": {"0x00": "0x01"}},
                 "target_storage": {"0xabc": {"0x08": "0x02"}}}
    assert application_gate(fixture(), requested, 2) == (
        False, "full-storage-override-forbidden")
    payload = fixture()
    payload["mutation_application"] *= 2
    assert not application_gate(payload, requested, 2)[0]


def test_code_copy_requires_nonempty_target_time_readback():
    requested = {"target_code_copy": {"0xshadow": "0xoracle"}}
    payload = {
        "prestate_proof_verified": True, "prefix_gas_match": True,
        "target_index": 2,
        "mutation_application": [{
            "kind": "code-copy", "address": "0xshadow", "source": "0xoracle",
            "before": "0x", "after": "0x6000", "target_index": 2,
            "prefix_completed": 2,
        }],
    }
    assert application_gate(payload, requested, 2) == (True, "application-verified")
    payload["mutation_application"][0]["after"] = "0x"
    assert application_gate(payload, requested, 2)[0] is False


def rows():
    return [
        {"mutation": "fidelity", "outcome": "EXECUTED", "fidelity_pass": True,
         "harm_S": "HARM", "harm_source": "pool_balance_delta", "harm_spec_id": "a"},
        {"mutation": "f_orc", "outcome": "EXECUTED", "harm_Sm": "NO_HARM",
         "harm_source_mutated": "pool_balance_delta", "harm_spec_id": "a",
         "intervention_valid": True, "mutation_application_verified": True,
         "mutation_contract_verified": True},
        {"mutation": "positive", "control_type": "positive", "control_pass": True,
         "harm_S": "HARM", "harm_source": "pool_balance_delta", "harm_spec_id": "a"},
        {"mutation": "sham", "control_type": "sham", "control_pass": True,
         "harm_Sm": "NO_HARM", "harm_source_mutated": "pool_balance_delta", "harm_spec_id": "a"}]


def test_policy_requires_each_gate_and_both_controls():
    evidence = rows()
    assert apply_policy_rows(evidence)[1]["verdict"] == "CAUSE"
    assert apply_policy_rows(evidence)[2]["verdict"] == "CONTROL_PASS"
    assert not apply_policy_rows(evidence)[2]["causal_evidence"]
    for field in ["mutation_application_verified", "mutation_contract_verified", "harm_spec_id"]:
        broken = deepcopy(evidence)
        broken[1].pop(field)
        assert apply_policy_rows(broken)[1]["verdict"] == "INCONCLUSIVE"
    for missing in [2, 3]:
        broken = deepcopy(evidence)
        broken.pop(missing)
        assert apply_policy_rows(broken)[1]["verdict"] == "INCONCLUSIVE"
    assert evidence == rows()


def test_audit_uses_live_policy(tmp_path):
    import json
    from eval.e4_policy_v2_audit import audit

    source = tmp_path / "source"
    source.mkdir()
    evidence = rows()
    (source / "systematic_subset_summary.json").write_text(json.dumps(
        {"results": [{"case_id": "fixture", "rows": evidence}]}))
    output = audit(source, tmp_path / "runs", "audit")
    audited = json.loads((output / "policy_v2_rows.json").read_text())
    live = apply_policy_rows(evidence)
    assert audited[0]["protocol_v2_decision"]["verdict"] == live[1]["verdict"]
    assert audited[0]["protocol_v2_decision"]["causal_evidence"] == live[1]["causal_evidence"]
