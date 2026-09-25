from eval.e4.causal_v3_protocol import (
    classify_v3_result, validate_blocking_evidence, validate_capital_substitution,
)

BASE = {
    "intervention_id": "fl-sub-1", "mechanism": "f_fl_capital_source",
    "capital_policy": "historical_only", "borrower": "0x" + "11" * 20,
    "asset_amounts": {"wbtc": "1"},
    "provider_seam": {"selector": "0x12345678", "preserved": True},
    "callback_contract": {"same_calldata": True, "same_borrower": True},
    "preserved_context": ["calldata", "prefix_state", "gas_limit", "dependencies"],
    "success_condition": "callback_reached", "stop_condition": "revert_or_complete",
}

def test_capital_substitution_contract():
    assert validate_capital_substitution(BASE) == (True, None)
    assert validate_capital_substitution(dict(BASE, capital_policy="seeded"))[0] is False

def test_blocking_evidence_requires_sham_and_first_divergence():
    evidence = {k: True for k in (
        "baseline_fidelity", "baseline_harm", "seam_match",
        "sham_execution_preserved", "sham_harm_preserved",
        "first_divergence_at_seam", "revert_at_or_downstream",
        "undeclared_mutation_absent")}
    evidence["committed_harm_counterfactual"] = False
    assert validate_blocking_evidence(evidence)[0] is True
    assert validate_blocking_evidence(dict(evidence, sham_harm_preserved=False))[0] is False

def test_v3_outcomes_are_fail_closed():
    assert classify_v3_result(baseline_harm="HARM", mutation_status="SUCCESS",
                              harm_mutated="NO_HARM", execution_comparable=True) == "CAUSE"
    assert classify_v3_result(baseline_harm="HARM", mutation_status="SUCCESS",
                              harm_mutated="HARM", execution_comparable=True) == "NOT_NECESSARY"
    assert classify_v3_result(baseline_harm="HARM", mutation_status="REVERTED",
                              harm_mutated="UNKNOWN", execution_comparable=False) == "INCONCLUSIVE_EXECUTION"
