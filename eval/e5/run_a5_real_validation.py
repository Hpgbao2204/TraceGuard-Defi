"""Classify real A5 evidence without promoting incomplete replay to validation."""

from __future__ import annotations

import json
import dataclasses
from pathlib import Path

from eval.e5.coupled_replay import (
    AuthorizationRegistry,
    CoupledInterventionPlan,
    prepare_replay,
)
from eval.e5.state_coupling import ConsistencyPredicate, StateEdge, StateNode


ROOT = Path(__file__).parents[2]
OUT = ROOT / "eval/results/e5_rcfh/a5_real_validation.json"


def _plan(*, predicates: tuple[ConsistencyPredicate, ...]) -> CoupledInterventionPlan:
    return CoupledInterventionPlan(
        plan_id="a5-alkimiya-wbtc-slot0",
        parent_state="proof:alkimiya:block-22146339",
        proof_bound=True,
        values={"borrower_balance": 1, "balance_slot0": 1},
        nodes=(
            StateNode("borrower_balance", "erc20_balance", "0x80bf7db69556d9521c03461978b8fc731dbbd4e4", "balanceOf" , "prestate_proof"),
            StateNode("balance_slot0", "storage", "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599", "slot0", "prestate_proof"),
        ),
        edges=(StateEdge("balance_slot0", "borrower_balance", "MIRRORS", "slot-resolver:proof-bound"),),
        predicates=predicates,
        seeds=("balance_slot0",),
    )


def _equal() -> ConsistencyPredicate:
    return ConsistencyPredicate(
        "alkimiya-wbtc-slot0-equal", "EQUAL",
        ("borrower_balance", "balance_slot0"),
        source="eval/results/e4_causal_v4/alkimiya_slot_resolution.json",
        confidence="HIGH", version="slot-resolver-v1",
    )


def main() -> None:
    replay = json.loads((ROOT / "eval/results/e5_rcfh/a4_alkimiya_morpho_real_replay.json").read_text())
    registry = AuthorizationRegistry()
    real_precheck = prepare_replay(
        _plan(predicates=(_equal(),)),
        backend=lambda plan, authorization: (
            registry.consume(plan, authorization),
            {"status": "PRECHECK_ONLY", "mutation_authorized": True},
        )[1],
    )
    real_precheck = {
        **real_precheck,
        "authorization": dataclasses.asdict(real_precheck["authorization"]),
    }
    positive_candidate = {
        "case_id": "alkimiya",
        "evidence": "proof-bound WBTC balance slot resolution + real Morpho replay",
        "state_gate": real_precheck,
        "replay": replay,
        "status": "INCONCLUSIVE_NONCOMPARABLE",
        "reason": "real counterfactual gas/log execution mismatch",
    }
    negative_candidate = {
        "case_id": "alkimiya-morpho-sham",
        "evidence": "same-kind sham acceptance",
        "status": "NOT_TESTABLE_NO_PROTECTED_OBSERVATION",
        "reason": "sham preserved execution but no protected harm observation was paired",
    }
    ambiguous = {
        "case_id": "alkimiya-missing-predicate-control",
        "state_gate": prepare_replay(_plan(predicates=()), backend=None),
        "status": "NOT_TESTABLE",
        "reason": "NO_CONSISTENCY_PREDICATE",
    }
    result = {
        "schema_version": 1,
        "artifact": "e5-a5-real-validation",
        "cases": [positive_candidate, negative_candidate, ambiguous],
        "counts": {"positive": 0, "negative": 0, "ambiguous": 1, "inconclusive": 2},
        "a5_gate": "NOT_COMPLETE",
        "reason": "no real case satisfies all replay-comparable and protected-observation gates",
        "causal_verdict": None,
    }
    OUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(OUT), "a5_gate": result["a5_gate"], "counts": result["counts"]}))


if __name__ == "__main__":
    main()
