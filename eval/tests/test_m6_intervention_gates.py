from eval.m6_intervention_gates import assess_revert_provenance, assess_execution

def test_revert_requires_all_provenance_gates():
    r = assess_revert_provenance(baseline_fidelity=True, sham_execution=True,
        mutation_applied=True, revert_after_seam=False, revert_reason_bound=True)
    assert r["status"] == "INCONCLUSIVE"

def test_revert_can_be_attributed_only_with_sham_and_binding():
    r = assess_revert_provenance(**{k: True for k in (
        "baseline_fidelity", "sham_execution", "mutation_applied",
        "revert_after_seam", "revert_reason_bound")})
    assert r["status"] == "REVERT_CAUSALLY_ATTRIBUTABLE"

def test_executable_harm_comparison_is_only_candidate():
    r = assess_execution(baseline_fidelity=True, sham_preserved=True,
        intervention_valid=True, counterfactual_executed=True,
        baseline_harm="HARM", counterfactual_harm="NO_HARM")
    assert r["verdict"] == "CAUSE_CANDIDATE"
