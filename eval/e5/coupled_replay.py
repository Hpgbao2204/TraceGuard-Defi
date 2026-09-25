"""A4 contract between state-coupling validation and replay backends."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Callable, Mapping

from eval.e5.state_coupling import (
    ConsistencyPredicate,
    StateEdge,
    StateNode,
    state_consistency_gate,
)


@dataclass(frozen=True)
class CoupledInterventionPlan:
    plan_id: str
    parent_state: str
    proof_bound: bool
    values: Mapping[str, int]
    nodes: tuple[StateNode, ...]
    edges: tuple[StateEdge, ...]
    predicates: tuple[ConsistencyPredicate, ...]
    seeds: tuple[str, ...]


@dataclass(frozen=True)
class ReplayAuthorization:
    """Evidence-bound capability issued by the pre-replay gate."""

    plan_hash: str
    case_id: str
    parent_state_root: str
    closure_hash: str
    predicate_evidence_hash: str
    authorized_scope: str = "STATE_CONSISTENCY_PRECHECK_ONLY"


class AuthorizationRegistry:
    """One-shot consumer for evidence-bound replay capabilities."""

    def __init__(self) -> None:
        self._consumed: set[str] = set()

    def consume(
        self,
        plan: CoupledInterventionPlan,
        authorization: ReplayAuthorization,
    ) -> None:
        expected = _authorization(plan, _gate_for_authorization(plan))
        if authorization != expected:
            raise ValueError("REPLAY_AUTHORIZATION_MISMATCH")
        if authorization.plan_hash in self._consumed:
            raise ValueError("REPLAY_AUTHORIZATION_ALREADY_CONSUMED")
        self._consumed.add(authorization.plan_hash)


def _authorization(plan: CoupledInterventionPlan, gate: Mapping[str, object]) -> ReplayAuthorization:
    payload = json.dumps({
        "plan_id": plan.plan_id,
        "parent_state": plan.parent_state,
        "closure": gate["closure"],
        "predicates": gate["predicate_result"],
    }, sort_keys=True, separators=(",", ":")).encode()
    plan_hash = hashlib.sha256(payload).hexdigest()
    closure_hash = hashlib.sha256(
        json.dumps(gate["closure"], separators=(",", ":")).encode()
    ).hexdigest()
    predicate_hash = hashlib.sha256(
        json.dumps(gate["predicate_result"], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return ReplayAuthorization(
        plan_hash=plan_hash,
        case_id=plan.plan_id,
        parent_state_root=plan.parent_state,
        closure_hash=closure_hash,
        predicate_evidence_hash=predicate_hash,
    )


def _gate_for_authorization(plan: CoupledInterventionPlan) -> dict[str, object]:
    gate = state_consistency_gate(
        plan.values, plan.nodes, plan.edges, plan.predicates, seeds=plan.seeds
    )
    if gate["status"] != "READY_FOR_REPLAY_PRECHECK":
        raise ValueError("REPLAY_AUTHORIZATION_PLAN_NOT_READY")
    return gate


def prepare_replay(
    plan: CoupledInterventionPlan,
    *,
    backend: Callable[[CoupledInterventionPlan, ReplayAuthorization], dict] | None = None,
) -> dict:
    """Validate a coupled plan and optionally hand it to a replay backend."""
    if not plan.plan_id or not plan.parent_state or not plan.proof_bound:
        return {
            "status": "NOT_TESTABLE",
            "reason": "PROOF_BOUND_PARENT_REQUIRED",
            "mutation_authorized": False,
        }
    gate = state_consistency_gate(
        plan.values,
        plan.nodes,
        plan.edges,
        plan.predicates,
        seeds=plan.seeds,
    )
    if gate["status"] != "READY_FOR_REPLAY_PRECHECK":
        return {
            "status": "NOT_TESTABLE",
            "reason": "STATE_CONSISTENCY_GATE_FAILED",
            "gate": gate,
            "mutation_authorized": False,
        }
    if backend is None:
        return {
            "status": "NOT_TESTABLE",
            "reason": "REPLAY_BACKEND_NOT_SUPPLIED",
            "gate": gate,
            "mutation_authorized": False,
        }
    authorization = _authorization(plan, gate)
    result = backend(plan, authorization)
    if not isinstance(result, dict):
        return {
            "status": "NOT_TESTABLE",
            "reason": "BACKEND_RESULT_MALFORMED",
            "gate": gate,
            "mutation_authorized": False,
        }
    return {
        "status": result.get("status", "NOT_TESTABLE"),
        "gate": gate,
        "backend_result": result,
        "authorization": authorization,
        # A backend cannot mint or escalate authorization. The pre-replay
        # capability is evidence-scoped and never means causal permission.
        "mutation_authorized": False,
    }
