"""Summarize the refined integer-percent VETH feasibility boundary."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "eval/results/e5_rcfh/veth_buyquote_dose_probe"
OUT = BASE / "feasibility_threshold.json"


def main() -> None:
    result = json.loads((BASE / "result.json").read_text())
    selected = [
        row for row in result["observations"]
        if row["dose_percent"] in {75, 76, 77, 80, 90, 100}
    ]
    statuses = {row["dose_percent"]: bool(row["actual_status"]) for row in selected}
    OUT.write_text(json.dumps({
        "schema_version": 1,
        "artifact": "e5-veth-feasibility-threshold",
        "case_id": "defihacklabs-veth-2024-11-14",
        "intervention": "coupled buyQuote amount and Factory msg.value scaling",
        "search_type": "integer-percent refinement",
        "observations": selected,
        "threshold": {
            "last_failing_integer_percent": 76,
            "first_successful_integer_percent": 77,
            "bracket": "[76%, 77%) at integer-percent resolution",
            "min_feasible_capital_ratio_not_exact": True,
        },
        "interpretation": (
            "The exploit path is not executable at 76% under the coupled "
            "intervention because the final repayment funding step fails. It "
            "is executable at 77% and above. This is a capital/repayment "
            "feasibility threshold, not evidence that the root mechanism is "
            "absent below the threshold and not a causal HarmVector verdict."
        ),
        "status": "FEASIBILITY_FLOOR_BRACKETED",
    }, indent=2) + "\n")
    print(OUT)


if __name__ == "__main__":
    main()
