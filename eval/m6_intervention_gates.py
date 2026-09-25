"""Fail-closed gates for interpreting intervention execution evidence."""

def assess_revert_provenance(*, baseline_fidelity, sham_execution,
                             mutation_applied, revert_after_seam,
                             revert_reason_bound):
    if not all(x is True for x in (baseline_fidelity, sham_execution,
                                   mutation_applied, revert_after_seam,
                                   revert_reason_bound)):
        return {"status": "INCONCLUSIVE", "reason": "REVERT_PROVENANCE_INCOMPLETE"}
    return {"status": "REVERT_CAUSALLY_ATTRIBUTABLE",
            "reason": "SHAM_PRESERVED_AND_REVERT_BOUND_TO_SEAM"}

def assess_execution(*, baseline_fidelity, sham_preserved, intervention_valid,
                     counterfactual_executed, baseline_harm, counterfactual_harm):
    if not all(x is True for x in (baseline_fidelity, sham_preserved, intervention_valid)):
        return {"verdict": "INCONCLUSIVE", "reason": "INTERVENTION_GATE_INCOMPLETE"}
    if not counterfactual_executed:
        return {"verdict": "INCONCLUSIVE", "reason": "COUNTERFACTUAL_NOT_EXECUTED"}
    if baseline_harm == "HARM" and counterfactual_harm == "NO_HARM":
        return {"verdict": "CAUSE_CANDIDATE", "reason": "HARM_REMOVED_UNDER_COMPARABLE_DETECTION"}
    if baseline_harm == "HARM" and counterfactual_harm == "HARM":
        return {"verdict": "NOT_NECESSARY", "reason": "HARM_PERSISTS"}
    return {"verdict": "INCONCLUSIVE", "reason": "HARM_COMPARISON_INCOMPLETE"}
