import pytest

from eval.m4_independent.normalize import normalize_relevant_state, relevant_state_hash


def test_state_diff_normalization_is_canonical_and_hashed():
    # This mirrors the Parity/Reth stateDiff shape: changed values are under
    # the '*' marker and contain from/to values.
    diff = {"0xAbC": {"balance": {"*": {"from": "0x01", "to": "0x02"}}, "storage": {"0x1": {"*": {"from": "0x00", "to": "0x0a"}}}}}
    required = {"0xabc": {"balance": True, "storage": {"0x" + "0" * 63 + "1": True}}}
    state = normalize_relevant_state(diff, required)
    assert state["0xabc"]["balance"] == "0x02"
    assert state["0xabc"]["storage"]["0x" + "0" * 63 + "1"] == "0x" + "0" * 63 + "a"
    assert len(relevant_state_hash(state)) == 64


def test_missing_required_cell_fails_closed():
    with pytest.raises(ValueError, match="required account"):
        normalize_relevant_state({}, {"0xabc": {"storage": {"0x" + "0" * 64: True}}})


@pytest.mark.parametrize("marker", ["=", "-"])
def test_non_value_state_diff_markers_fail_closed(marker):
    diff = {"0xabc": {"balance": marker}}
    with pytest.raises(ValueError):
        normalize_relevant_state(diff, {"0xabc": {"balance": True}})


def test_unchanged_marker_uses_independent_prestate():
    diff = {"0xabc": {"balance": "="}}
    baseline = {"0xabc": {"balance": "0x01"}}
    state = normalize_relevant_state(diff, {"0xabc": {"balance": True}}, baseline)
    assert state["0xabc"]["balance"] == "0x01"


def test_added_state_diff_marker_uses_post_value():
    diff = {"0xabc": {"balance": {"+": "0x2"}}}
    state = normalize_relevant_state(diff, {"0xabc": {"balance": True}})
    assert state["0xabc"]["balance"] == "0x2"
