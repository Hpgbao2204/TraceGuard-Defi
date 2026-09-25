"""Fail-closed Stage-2 outcome and comparability contracts."""

from __future__ import annotations

from typing import Any, Mapping

from eval.causal_slice import assert_non_circular_outcome


def topology_gate(observation: Mapping[str, Any]) -> str:
    """Classify boundary comparability without requiring identical topology."""
    if not observation.get("intervention_seam_match", False):
        return "NONCOMPARABLE"
    if not observation.get("same_kind_sham_pass", False):
        return "NONCOMPARABLE"
    if observation.get("unexpected_early_divergence", False):
        return "NONCOMPARABLE"
    if observation.get("blocking_point_reached", False) and observation.get("sink_committed", False) is False:
        return "BLOCKING_COMPARABLE"
    if observation.get("causal_prefix_preserved", False) and observation.get("outcome_boundary_observable", False):
        return "COMPARABLE"
    return "NONCOMPARABLE"


def vector_difference(before: Mapping[str, int], after: Mapping[str, int]) -> dict[str, int]:
    assets = set(before) | set(after)
    return {asset: int(after.get(asset, 0)) - int(before.get(asset, 0)) for asset in sorted(assets)}


def attack_verdict(factual: Mapping[str, Any], counterfactual: Mapping[str, Any]) -> str:
    gate = counterfactual.get("topology_gate")
    if gate not in {"COMPARABLE", "BLOCKING_COMPARABLE"}:
        return "NOT_TESTABLE"
    if not factual.get("downstream_predicates"): 
        return "NOT_TESTABLE"
    if any(factual["downstream_predicates"].get(k) is True and counterfactual.get("downstream_predicates", {}).get(k) is True for k in factual["downstream_predicates"]):
        factual_vec = factual.get("extraction_vector", {})
        cf_vec = counterfactual.get("extraction_vector", {})
        if factual_vec == cf_vec:
            return "ATTACK_PERSISTS"
        return "PARTIAL_EFFECT"
    if any(v is True for v in factual["downstream_predicates"].values()):
        return "ATTACK_OUTCOME_REMOVED"
    return "NOT_TESTABLE"
