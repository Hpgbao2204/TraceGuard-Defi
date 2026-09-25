"""Materialize the preregistered P0/P1 pilot from existing evidence only.

No RPC, mutation, or inferred label is performed here. Missing evidence is
explicitly represented as NOT_TESTABLE.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from eval.security_property import derive_outcome


REGISTRY = ROOT / "eval/results/e5_rcfh/security_property_registry_v1.json"
OUT = ROOT / "eval/results/e5_rcfh/security_property_pilot_v1.json"


def main() -> None:
    registry = json.loads(REGISTRY.read_text())
    observations = [
        {
            "property_id": "alkimiya-value-within-uint128-range",
            "case_id": "alkimiya",
            "property_kind": "TYPE_SAFETY",
            "factual": {
                "execution": "EXECUTED",
                "property_violated": True,
                "evidence": "m6_alkimiya_FINAL_verdict.json: shares input 2^128+1",
            },
            "counterfactual": {
                "execution": "BLOCKED_AT_DECLARED_BOUNDARY",
                "comparable": False,
                "property_violated": False,
                "blocking_boundary_reached": True,
                "evidence": "m6_alkimiya_FINAL_verdict.json: SharesTooLarge, no state commit",
            },
            "evidence_class": "existing_canonical_blocking_artifact",
        },
        {
            "property_id": "mure-trusted-signer-binding",
            "case_id": "defihacklabs-muredistribution-2026-05-21",
            "property_kind": "AUTHORIZATION",
            "factual": {
                "execution": "EXECUTED",
                "property_violated": True,
                "evidence": "muredistribution_boundary_materialized.json: caller-supplied signer returns ERC1271 magic value before committed QUEST transfer",
            },
            "counterfactual": {
                "execution": "BLOCKED_AT_DECLARED_BOUNDARY",
                "comparable": False,
                "blocking_boundary_reached": True,
                "property_violated": False,
                "evidence": "mure_erc1271_final_verdict.json: validation substitution reverted target and emitted no committed transfer",
            },
            "evidence_class": "existing_canonical_blocking_artifact",
        },
        {
            "property_id": "oracle-valuation-source-valid",
            "case_id": "defihacklabs-onyxdao-2024-09-26",
            "property_kind": "VALUATION_SOURCE",
            "factual": {
                "execution": "EXECUTED",
                "property_violated": None,
                "evidence": "oracle intervention evidence exists, but property-specific factual violation is not adjudicated",
            },
            "counterfactual": {
                "execution": "NOT_RUN",
                "comparable": False,
                "property_violated": None,
                "evidence": "no property-specific comparable observation",
            },
            "evidence_class": "baseline_property_not_observed",
        },
    ]
    for row in observations:
        row["outcome"] = derive_outcome(row)
        row["policy"] = "no_harm_or_profit_proxy; no_generic_revert_as_safe"
    counts = {}
    for row in observations:
        counts[row["outcome"]] = counts.get(row["outcome"], 0) + 1
    result = {
        "schema_version": "security-property-pilot-v1",
        "registry": str(REGISTRY.relative_to(ROOT)),
        "status": "PILOT_MATERIALIZED_FROM_EXISTING_EVIDENCE",
        "replay_performed": False,
        "case_count": len(observations),
        "outcome_counts": counts,
        "observations": observations,
        "comparison": {
            "property_baseline_observable": 1,
            "property_verdictable": 1,
            "harm_verdictable": "not recomputed in this pilot",
            "interpretation": "property evidence exists for one preregistered blocking case; this is not a comparative efficacy estimate",
        },
        "registry_snapshot": registry["schema_version"],
    }
    OUT.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"output": str(OUT), "outcome_counts": counts}, indent=2))


if __name__ == "__main__":
    main()
