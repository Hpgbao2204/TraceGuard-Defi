"""Validation for execution-preserving semantic substitutions."""

REQUIRED = ("intervention_id", "mechanism", "replacement", "capital_policy",
            "preserved_context", "success_condition", "stop_condition")

def validate_substitution(spec):
    if not isinstance(spec, dict):
        return False, "spec_missing"
    missing = [key for key in REQUIRED if not spec.get(key)]
    if missing:
        return False, "missing:" + ",".join(missing)
    if spec.get("capital_policy") != "historical_only":
        return False, "capital_policy_not_frozen"
    preserved = set(spec.get("preserved_context") or [])
    required = {"calldata", "prefix_state", "gas_limit", "dependencies"}
    if not required.issubset(preserved):
        return False, "preserved_context_incomplete"
    return True, None
