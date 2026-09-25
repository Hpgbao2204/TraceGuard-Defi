from eval.security_property import derive_outcome, validate_observation


def _record(counterfactual):
    return {
        "property_id": "p",
        "case_id": "c",
        "property_kind": "AUTHORIZATION",
        "factual": {"execution": "EXECUTED", "property_violated": True},
        "counterfactual": counterfactual,
    }


def test_violation_removed_requires_comparable_execution():
    assert derive_outcome(_record({"execution": "EXECUTED", "comparable": True, "property_violated": False})) == "VIOLATION_REMOVED"


def test_declared_blocking_boundary_is_separate_outcome():
    assert derive_outcome(_record({"execution": "BLOCKED_AT_DECLARED_BOUNDARY", "comparable": False, "property_violated": False, "blocking_boundary_reached": True})) == "VIOLATION_REMOVED_BLOCKING"


def test_revert_is_not_safe():
    assert derive_outcome(_record({"execution": "REVERTED", "comparable": False, "property_violated": False})) == "NOT_OBSERVABLE"


def test_schema_rejects_missing_baseline_observation():
    record = _record({"execution": "EXECUTED", "comparable": True})
    assert "counterfactual:missing:property_violated" in validate_observation(record)
