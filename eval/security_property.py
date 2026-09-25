"""Fail-closed schema helpers for property-based falsification.

This module records contextual property observations. It does not infer
causality and it does not turn a revert into a safe outcome.
"""

from __future__ import annotations

from typing import Any, Mapping


TERMINAL_OUTCOMES = {
    "VIOLATION_REMOVED",
    "VIOLATION_REMOVED_BLOCKING",
    "VIOLATION_PERSISTS",
    "VIOLATION_PARTIALLY_CHANGED",
    "NOT_OBSERVABLE",
}


def validate_observation(record: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in ("property_id", "case_id", "property_kind", "factual", "counterfactual"):
        if key not in record:
            errors.append(f"missing:{key}")
    for side in ("factual", "counterfactual"):
        value = record.get(side)
        if not isinstance(value, Mapping):
            errors.append(f"{side}:not_object")
            continue
        if "execution" not in value:
            errors.append(f"{side}:missing:execution")
        if "property_violated" not in value:
            errors.append(f"{side}:missing:property_violated")
    outcome = record.get("outcome")
    if outcome is not None and outcome not in TERMINAL_OUTCOMES:
        errors.append(f"invalid:outcome:{outcome}")
    return errors


def derive_outcome(record: Mapping[str, Any]) -> str:
    """Derive only from explicit comparable observations; otherwise abstain."""
    errors = validate_observation(record)
    if errors:
        return "NOT_OBSERVABLE"
    factual = record["factual"]
    counterfactual = record["counterfactual"]
    if counterfactual.get("blocking_boundary_reached") is True:
        if factual["property_violated"] is True and counterfactual["property_violated"] is False:
            return "VIOLATION_REMOVED_BLOCKING"
        return "NOT_OBSERVABLE"
    if counterfactual.get("execution") != "EXECUTED" or not counterfactual.get("comparable", False):
        return "NOT_OBSERVABLE"
    if factual["property_violated"] is True and counterfactual["property_violated"] is False:
        return "VIOLATION_REMOVED"
    if factual["property_violated"] is True and counterfactual["property_violated"] is True:
        return "VIOLATION_PERSISTS"
    return "VIOLATION_PARTIALLY_CHANGED"
