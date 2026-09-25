import pytest

from eval.e5.guard_synthesis import (
    GuardError,
    GuardSpec,
    assess_guard_regression,
    synthesize_precondition,
)


def _spec(**overrides):
    values = dict(
        guard_id="g-erc1271",
        boundary="distribution.signer",
        selector="0x1626ba7e",
        field="signer",
        operator="EQUALS",
        expected="trusted-signer",
        protected_objective="prevent unauthorized token transfer",
        necessity_supported=True,
        evidence_id="evidence:fixture:1",
        provenance="reviewer-c:fixture-v1",
    )
    values.update(overrides)
    return GuardSpec(**values)


def test_guard_ir_blocks_attack_and_preserves_benign_calls():
    spec = _spec()
    result = assess_guard_regression(
        spec,
        attack_context={"signer": "attacker-signer"},
        benign_contexts=[{"signer": "trusted-signer"}],
    )
    assert result["status"] == "VALIDATED_GUARD"
    assert result["attack_blocked"] is True
    assert result["benign_preserved"] is True
    assert synthesize_precondition(spec)["deployed"] is False


def test_guard_requires_supported_necessity_and_provenance():
    with pytest.raises(GuardError):
        synthesize_precondition(_spec(necessity_supported=False))
    with pytest.raises(GuardError):
        synthesize_precondition(_spec(provenance=None))


def test_benign_regression_fails_closed():
    result = assess_guard_regression(
        _spec(),
        attack_context={"signer": "attacker-signer"},
        benign_contexts=[
            {"signer": "trusted-signer"},
            {"signer": "another-valid-signer"},
        ],
    )
    assert result["status"] == "GUARD_REGRESSION_FAILED"


def test_empty_benign_regression_is_not_testable():
    result = assess_guard_regression(
        _spec(), attack_context={"signer": "attacker-signer"}, benign_contexts=[]
    )
    assert result["status"] == "NOT_TESTABLE_NO_BENIGN_CONTROL"


def test_arithmetic_guard_synthetic_control():
    spec = _spec(
        guard_id="g-shares-uint128",
        boundary="silicaPools.shares",
        selector="0x71e109d4",
        field="shares",
        operator="MAX_VALUE",
        expected=str((1 << 128) - 1),
        protected_objective="prevent downcast-induced accounting loss",
    )
    result = assess_guard_regression(
        spec,
        attack_context={"shares": str((1 << 128) + 1)},
        benign_contexts=[{"shares": "1"}, {"shares": str(1 << 64)}],
    )
    assert result["status"] == "VALIDATED_GUARD"
