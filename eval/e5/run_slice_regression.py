"""Regression checks for automatic slicing and relaxed prefix validity."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from eval.causal_slice import assert_non_circular_outcome, assert_prefix_match


OUT = ROOT / "eval/results/e5_rcfh/causal_slice_regression_v1.json"


def target_row(path: Path, index: int | None = None) -> dict:
    data = json.loads(path.read_text())
    rows = data["per_tx"]
    return rows[data.get("target_index", len(rows) - 1) if index is None else index]


def main() -> None:
    veth_a = target_row(ROOT / "eval/results/e5_rcfh/veth_buyquote_dose_probe/dose_100.json")
    veth_b = target_row(ROOT / "eval/results/e5_rcfh/veth_buyquote_dose_probe/dose_095.json")
    # The dose is injected at the buyQuote/primary path entry (17). Trace 45
    # is a later sibling boundary and is intentionally not the prefix gate.
    dose_prefix = assert_prefix_match(veth_a["call_trace"], veth_b["call_trace"], 17)
    root_boundary_probe = assert_prefix_match(veth_a["call_trace"], veth_b["call_trace"], 45)
    veth_baseline = target_row(ROOT / "eval/results/m4/b2-contexts-fresh/defihacklabs-veth-2024-11-14/b2-replay-m4.json", 57)
    four_cell = target_row(ROOT / "eval/results/e5_rcfh/veth_buyquote_dose_probe/settlement_entry_storage_patch_real_four_cells.json", 57)
    four_cell_prefix = assert_prefix_match(veth_baseline["call_trace"], four_cell["call_trace"], 77)
    assert_non_circular_outcome(["erc1271_return"], ["committed_transfer", "extraction_vector"])

    summer = target_row(ROOT / "eval/results/m4/b2-contexts-fresh/defihacklabs-summerfi-2026-07-06/b2-replay-m4.json")
    selectors = {str(e.get("input", ""))[:10].lower() for e in summer["call_trace"] if e.get("event") == "enter"}
    result = {
        "schema_version": "causal-slice-regression-v1",
        "veth": {
            "status": "PASS_FOR_DOSE_INTERVENTION_ONLY",
            "claim_binding_required": True,
            "dose_input_intervention": {
                "trace_index": 17,
                "selector": "0xa7591849",
                "prefix": dose_prefix,
                "interpretation": "dose pair diverges at the buyQuote/primary path; this is not the VETH root-boundary claim",
            },
            "root_boundary_reference": {
                "trace_index": 45,
                "selector": "0x6c0472da",
                "prefix_probe_against_dose_pair": root_boundary_probe,
                "interpretation": "trace 45 is the separately bound virtual-liquidity/helper boundary; dose pair is not a valid counterfactual for claiming its prefix",
            },
            "four_cell_claim_bound_probe": {
                "intervention_index": 77,
                "prefix": four_cell_prefix,
                "status": "PASS_PREFIX_GATE",
                "interpretation": "the available four-cell counterfactual preserves the prefix to its actual storage intervention at trace 77; it does not prove a trace-45 helper intervention",
            },
            "trace_45_artifact_status": "NOT_AVAILABLE_FOR_DIRECT_COUNTERFACTUAL_PREFIX_CHECK",
            "known_semantic_reference": "VETH dose/value-flow and virtual-liquidity audits",
        },
        "summerfi": {
            "status": "BASELINE_EXTRACTION_ONLY",
            "counterfactual_prefix": "NOT_TESTABLE_NO_FROZEN_COMPARABLE_COUNTERFACTUAL",
            "known_nav_selector_observed": "0x01e1d114" in selectors,
            "known_semantic_reference": "summerfi_nav_trace_audit.json",
            "interpretation": "baseline trace is available for extractor regression, but no causal verdict is inferred",
        },
        "non_circularity_check": "PASS",
        "not_claimed": ["VETH root cause automatically discovered", "SummerFi causal result", "exact topology equality globally"],
    }
    OUT.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"veth_dose": dose_prefix, "veth_root_probe": root_boundary_probe, "summerfi_nav_selector": "0x01e1d114" in selectors}, indent=2))


if __name__ == "__main__":
    main()
