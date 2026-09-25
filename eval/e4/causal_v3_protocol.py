"""Preregistered contracts for E4 causal-v3 pilots.

These validators are deliberately pure.  They authorize evidence shapes; they
do not manufacture a callback trampoline or infer harm from a reverted run.
"""
from __future__ import annotations

REQUIRED_SUBSTITUTION = {
    "intervention_id", "mechanism", "capital_policy", "borrower",
    "asset_amounts", "provider_seam", "callback_contract", "preserved_context",
    "success_condition", "stop_condition",
}
REQUIRED_CONTEXT = {"calldata", "prefix_state", "gas_limit", "dependencies"}

def validate_capital_substitution(spec):
    if not isinstance(spec, dict):
        return False, "spec_missing"
    missing = sorted(REQUIRED_SUBSTITUTION - set(spec))
    if missing:
        return False, "missing:" + ",".join(missing)
    if spec.get("mechanism") != "f_fl_capital_source":
        return False, "wrong_mechanism"
    if spec.get("capital_policy") != "historical_only":
        return False, "capital_policy_not_historical_only"
    if not spec.get("borrower") or not spec.get("asset_amounts"):
        return False, "borrower_or_assets_missing"
    if not isinstance(spec.get("provider_seam"), dict) or not spec["provider_seam"].get("selector"):
        return False, "provider_seam_missing"
    if not isinstance(spec.get("callback_contract"), dict) or not spec["callback_contract"].get("same_calldata"):
        return False, "callback_contract_missing"
    if not REQUIRED_CONTEXT.issubset(set(spec.get("preserved_context") or [])):
        return False, "preserved_context_incomplete"
    return True, None

def validate_blocking_evidence(evidence):
    """Validate blocking necessity evidence without calling it generic CAUSE."""
    if not isinstance(evidence, dict):
        return False, "evidence_missing"
    required = ("baseline_fidelity", "baseline_harm", "seam_match",
                "sham_execution_preserved", "sham_harm_preserved",
                "first_divergence_at_seam", "revert_at_or_downstream",
                "undeclared_mutation_absent", "committed_harm_counterfactual")
    missing = [x for x in required if x not in evidence]
    if missing:
        return False, "missing:" + ",".join(missing)
    if not all(evidence[x] is True for x in required[:-1]):
        return False, "blocking_gate_failed"
    if evidence["committed_harm_counterfactual"] is not False:
        return False, "counterfactual_harm_not_removed"
    return True, "CAUSE-NECESSARY-blocking-eligible"

def classify_v3_result(*, baseline_harm, mutation_status, harm_mutated,
                       execution_comparable, blocking_evidence=None):
    if baseline_harm != "HARM":
        return "NOT_EVALUABLE"
    if blocking_evidence is not None:
        ok, _ = validate_blocking_evidence(blocking_evidence)
        if ok:
            return "CAUSE"
    if not execution_comparable or mutation_status != "SUCCESS":
        return "INCONCLUSIVE_EXECUTION"
    if harm_mutated == "NO_HARM":
        return "CAUSE"
    if harm_mutated == "HARM":
        return "NOT_NECESSARY"
    return "INCONCLUSIVE_OBSERVATION"
