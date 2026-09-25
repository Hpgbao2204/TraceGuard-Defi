from eval.e4.verdict import evaluate_blocking_revert_v4


BASE = {("victim", "WETH"): -10}


def kwargs(**overrides):
    value = dict(
        baseline_hard=BASE,
        counterfactual_reverted=True,
        seam_match_count=1,
        intervention_applied=True,
        same_kind_sham_pass=True,
        callback_postconditions_pass=True,
        footprint_pass=True,
        counterfactual_neg=set(),
        target=("victim", "WETH"),
    )
    value.update(overrides)
    return value


def test_valid_blocking_revert_is_cause():
    assert evaluate_blocking_revert_v4(**kwargs()) == "CAUSE-NECESSARY-blocking"


def test_revert_without_sham_is_inconclusive():
    assert evaluate_blocking_revert_v4(**kwargs(same_kind_sham_pass=False)) == "INCONCLUSIVE_SHAM"


def test_revert_with_remaining_negative_effect_is_inconclusive():
    assert evaluate_blocking_revert_v4(**kwargs(counterfactual_neg=BASE.keys())) == "INCONCLUSIVE_HARM_REMAINS"


def test_revert_without_baseline_harm_is_inconclusive():
    assert evaluate_blocking_revert_v4(**kwargs(baseline_hard={})) == "INCONCLUSIVE_BASELINE_HARM"
