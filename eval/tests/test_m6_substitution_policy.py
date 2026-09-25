from eval.m6_substitution_policy import validate_substitution

BASE = {"intervention_id":"i", "mechanism":"oracle", "replacement":"pre_manipulation",
        "capital_policy":"historical_only",
        "preserved_context":["calldata","prefix_state","gas_limit","dependencies"],
        "success_condition":"execute_to_harm_observation", "stop_condition":"revert_or_complete"}

def test_valid_substitution():
    assert validate_substitution(BASE) == (True, None)

def test_seeded_policy_rejected():
    spec = dict(BASE, capital_policy="seeded")
    assert validate_substitution(spec)[0] is False

def test_missing_context_rejected():
    spec = dict(BASE, preserved_context=["calldata"])
    assert validate_substitution(spec)[0] is False
