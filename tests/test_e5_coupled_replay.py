import dataclasses

import pytest

from eval.e5.coupled_replay import (
    AuthorizationRegistry,
    CoupledInterventionPlan,
    prepare_replay,
)
from eval.e5.state_coupling import ConsistencyPredicate, StateEdge, StateNode


def _plan(proof_bound=True):
    return CoupledInterventionPlan(
        plan_id="plan-fixture",
        parent_state="proof:parent",
        proof_bound=proof_bound,
        values={"reserve": 10, "balance": 10},
        nodes=(
            StateNode("reserve", "storage", "0xpool", "0x1"),
            StateNode("balance", "erc20_balance", "0xpool", "0xtoken"),
        ),
        edges=(
            StateEdge("reserve", "balance", "CONSISTENCY_REQUIRES", "fixture"),
        ),
        predicates=(
            ConsistencyPredicate(
                "equal", "EQUAL", ("reserve", "balance"),
                source="fixture", confidence="HIGH", version="v1",
            ),
        ),
        seeds=("reserve",),
    )


def test_a4_rejects_without_backend_or_proof():
    assert prepare_replay(_plan())["reason"] == "REPLAY_BACKEND_NOT_SUPPLIED"
    assert prepare_replay(_plan(False))["reason"] == "PROOF_BOUND_PARENT_REQUIRED"


def test_a4_passes_validated_plan_to_backend_without_claiming_authority():
    seen = []

    def backend(plan, authorization):
        seen.append(plan.plan_id)
        assert authorization.case_id == "plan-fixture"
        assert authorization.authorized_scope == "STATE_CONSISTENCY_PRECHECK_ONLY"
        return {"status": "EXECUTED_DIAGNOSTIC", "mutation_authorized": False}

    result = prepare_replay(_plan(), backend=backend)
    assert result["status"] == "EXECUTED_DIAGNOSTIC"
    assert result["gate"]["closure"] == ("balance", "reserve")
    assert result["mutation_authorized"] is False
    assert seen == ["plan-fixture"]


def test_authorization_rejects_plan_parent_closure_and_predicate_changes():
    plan = _plan()
    captured = {}

    def backend(received, authorization):
        captured["authorization"] = authorization
        return {"status": "EXECUTED_DIAGNOSTIC", "mutation_authorized": True}

    result = prepare_replay(plan, backend=backend)
    auth = result["authorization"]
    registry = AuthorizationRegistry()
    registry.consume(plan, auth)
    assert result["mutation_authorized"] is False
    for changed in (
        dataclasses.replace(plan, plan_id="changed"),
        dataclasses.replace(plan, parent_state="changed"),
        dataclasses.replace(plan, seeds=("balance",)),
        dataclasses.replace(plan, predicates=()),
    ):
        with pytest.raises(ValueError):
            registry.consume(changed, auth)
    with pytest.raises(ValueError, match="ALREADY_CONSUMED"):
        registry.consume(plan, auth)
