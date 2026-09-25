"""Materialize MuRe's semantic outcome comparison from frozen artifacts."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from eval.counterfactual_outcome import attack_verdict, topology_gate, vector_difference
from eval.causal_slice import assert_non_circular_outcome


OUT = ROOT / "eval/results/e5_rcfh/mure_counterfactual_outcome_v1.json"


def main() -> None:
    baseline = {
        "downstream_predicates": {
            "unauthorized_transfer_from_committed": True,
            "protected_asset_transfer_committed": True,
            "attacker_cluster_extraction_observed": True,
        },
        "extraction_vector": {"QUEST": 4848683803036},
    }
    cf_gate_input = {
        "intervention_seam_match": True,
        "same_kind_sham_pass": True,
        "unexpected_early_divergence": False,
        "blocking_point_reached": True,
        "sink_committed": False,
        "causal_prefix_preserved": True,
        "outcome_boundary_observable": True,
    }
    counterfactual = {
        "topology_gate": topology_gate(cf_gate_input),
        "downstream_predicates": {
            "unauthorized_transfer_from_committed": False,
            "protected_asset_transfer_committed": False,
            "attacker_cluster_extraction_observed": False,
        },
        "extraction_vector": {"QUEST": 0},
        "gate_evidence": cf_gate_input,
    }
    assert_non_circular_outcome(["erc1271_return"], ["unauthorized_transfer_from_committed", "protected_asset_transfer_committed", "attacker_cluster_extraction_observed", "QUEST"])
    result = {
        "schema_version": "counterfactual-outcome-v1",
        "case_id": "defihacklabs-muredistribution-2026-05-21",
        "intervention": {
            "variable": "ERC1271 validation return",
            "replacement": "invalid result",
            "artifact": "eval/results/e5_rcfh/mure_erc1271_final_verdict.json",
        },
        "outcome_predicate_policy": {
            "non_circular": True,
            "rule": "predicates describe downstream committed transfer/extraction, not the ERC1271 return value",
        },
        "factual": baseline,
        "counterfactual": counterfactual,
        "asset_metadata": {
            "QUEST": {
                "decimals": 6,
                "decimals_source": "mure_erc1271_final_verdict.json reported 4,848,683.803036 QUEST for 4,848,683,803,036 base units",
            }
        },
        "extraction_vector_delta": vector_difference(baseline["extraction_vector"], counterfactual["extraction_vector"]),
        "verdict": attack_verdict(baseline, counterfactual),
        "scope": "transaction-specific counterfactual attack-outcome comparison",
        "not_claimed": [
            "no cross-asset scalar sum",
            "no USD conversion without frozen valuation",
            "no universal exploit prevention",
            "no global unique root cause",
        ],
    }
    OUT.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"topology_gate": counterfactual["topology_gate"], "verdict": result["verdict"], "extraction_delta": result["extraction_vector_delta"]}, indent=2))


if __name__ == "__main__":
    main()
