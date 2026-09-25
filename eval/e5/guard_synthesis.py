"""Fail-closed replay-validated guard IR and executable precondition guards."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


class GuardError(ValueError):
    pass


@dataclass(frozen=True)
class GuardSpec:
    guard_id: str
    boundary: str
    selector: str
    field: str
    operator: str
    expected: str
    protected_objective: str
    necessity_supported: bool
    evidence_id: str
    provenance: str | None


SUPPORTED_OPERATORS = frozenset({"EQUALS", "NOT_EQUALS", "IN_SET", "MAX_VALUE"})


def validate_guard_spec(spec: GuardSpec) -> None:
    if not spec.guard_id or not spec.boundary or not spec.selector:
        raise GuardError("guard identity and boundary are required")
    if spec.operator not in SUPPORTED_OPERATORS:
        raise GuardError("unsupported guard operator")
    if not spec.field or not spec.expected:
        raise GuardError("guard condition is incomplete")
    if not spec.protected_objective or not spec.evidence_id:
        raise GuardError("protected objective and evidence binding are required")
    if not spec.provenance:
        raise GuardError("guard provenance is required")
    if not spec.necessity_supported:
        raise GuardError("guard requires supported necessity evidence")


def evaluate_guard(spec: GuardSpec, context: Mapping[str, object]) -> bool:
    """Return True when the call is allowed by the guard."""
    validate_guard_spec(spec)
    if spec.field not in context:
        raise GuardError(f"guard context missing field: {spec.field}")
    value = str(context[spec.field]).lower()
    expected = spec.expected.lower()
    if spec.operator == "EQUALS":
        return value == expected
    if spec.operator == "NOT_EQUALS":
        return value != expected
    if spec.operator == "IN_SET":
        return value in {item.strip().lower() for item in expected.split(",")}
    if spec.operator == "MAX_VALUE":
        try:
            return int(value, 0) <= int(expected, 0)
        except ValueError as exc:
            raise GuardError("MAX_VALUE requires integer context and bound") from exc
    raise GuardError("unreachable guard operator")


def synthesize_precondition(spec: GuardSpec) -> dict[str, object]:
    """Create a reviewable Solidity-like guard IR, not deployed bytecode."""
    validate_guard_spec(spec)
    if spec.operator == "EQUALS":
        expression = f"{spec.field} == {spec.expected}"
    elif spec.operator == "NOT_EQUALS":
        expression = f"{spec.field} != {spec.expected}"
    else:
        expression = (
            f"allowed({spec.field}, {spec.expected})"
            if spec.operator == "IN_SET"
            else f"{spec.field} <= {spec.expected}"
        )
    return {
        "schema_version": 1,
        "guard_id": spec.guard_id,
        "kind": "PRECONDITION",
        "boundary": spec.boundary,
        "selector": spec.selector,
        "condition": expression,
        "on_failure": "REVERT",
        "protected_objective": spec.protected_objective,
        "evidence_id": spec.evidence_id,
        "provenance": spec.provenance,
        "executable": True,
        "deployed": False,
    }


def assess_guard_regression(
    spec: GuardSpec,
    *,
    attack_context: Mapping[str, object],
    benign_contexts: list[Mapping[str, object]],
) -> dict[str, object]:
    """Check attack blocking and benign preservation for the IR policy."""
    if not benign_contexts:
        return {
            "status": "NOT_TESTABLE_NO_BENIGN_CONTROL",
            "attack_blocked": None,
            "benign_preserved": None,
            "guard_id": spec.guard_id,
            "evidence_id": spec.evidence_id,
            "reason": "NO_BENIGN_CONTROL",
        }
    blocked = not evaluate_guard(spec, attack_context)
    benign_preserved = all(evaluate_guard(spec, item) for item in benign_contexts)
    return {
        "status": (
            "VALIDATED_GUARD"
            if blocked and benign_preserved
            else "GUARD_REGRESSION_FAILED"
        ),
        "attack_blocked": blocked,
        "benign_preserved": benign_preserved,
        "guard_id": spec.guard_id,
        "evidence_id": spec.evidence_id,
    }
