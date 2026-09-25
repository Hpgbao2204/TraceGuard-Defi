from eval.e4.falsification_protocol import (
    DoseObservation,
    FalsificationLabel,
    NecessityClaim,
    classify_dose_response,
)


def test_claim_is_context_bound_and_labels_are_explicit():
    claim = NecessityClaim("tx", "ctx", "amm.reserve", "victim.weth", "M necessary for H")
    assert claim.context_id == "ctx"
    assert FalsificationLabel.NOT_TESTABLE.value == "NOT_TESTABLE"


def test_revert_is_not_encoded_as_zero_harm():
    observations = [
        DoseObservation("x1", "reserve_ratio", "1.0", "EXECUTED", "COMPARABLE", {"pool|weth": -100}),
        DoseObservation("x2", "reserve_ratio", "0.7", "REVERTED", "NOT_COMPARABLE", None, "SLIPPAGE_REVERT"),
    ]
    assert observations[1].y["H"] is None
    assert classify_dose_response(observations) == "RESPONSE_WITH_FEASIBILITY_BOUNDARY"
