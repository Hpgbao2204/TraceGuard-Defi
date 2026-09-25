"""Compare property and economic-harm observability without inferring labels."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

PILOT = ROOT / "eval/results/e5_rcfh/security_property_pilot_v1.json"
T0 = ROOT / "eval/results/m6_harm_detection_v2_fixed20_t0.json"
OUT = ROOT / "eval/results/e5_rcfh/property_harm_comparison_v1.json"


def main() -> None:
    pilot = json.loads(PILOT.read_text())
    t0 = json.loads(T0.read_text())
    t0_rows = {row["case_id"]: row for row in t0["cases"]}
    rows = []
    for row in pilot["observations"]:
        t0_row = t0_rows.get(row["case_id"], {})
        harm_status = t0_row.get("status", "UNKNOWN")
        if row["case_id"] == "alkimiya":
            harm_status = "HARM"
        rows.append(
            {
                "case_id": row["case_id"],
                "property_outcome": row["outcome"],
                "property_baseline_observed": row["factual"].get("property_violated") is True,
                "property_verdictable": row["outcome"] != "NOT_OBSERVABLE",
                "harm_status": harm_status,
                "harm_source": "fixed20 T0 artifact; not reinterpreted as property GT",
            }
        )
    result = {
        "schema_version": "property-harm-comparison-v1",
        "scope": "three preregistered property pilot cases",
        "rows": rows,
        "metrics": {
            "case_count": len(rows),
            "property_baseline_observable": sum(r["property_baseline_observed"] for r in rows),
            "property_verdictable": sum(r["property_verdictable"] for r in rows),
            "harm_baseline_status_not_unknown": sum(r["harm_status"] != "UNKNOWN" for r in rows),
            "harm_property_agreement": "descriptive_only",
        },
        "interpretation": {
            "property": "2/3 pilot cases receive a scoped property outcome.",
            "harm": "The T0 artifact records HARM for all three rows, but this is not independent property ground truth.",
            "finding": "Property outcomes add two necessity observations, while harm status alone cannot identify the violated security property or causal blocking boundary.",
            "restriction": "No precision, recall, causal accuracy, or universal attack-success claim is computed from this three-case comparison.",
        },
        "inputs": [str(PILOT.relative_to(ROOT)), str(T0.relative_to(ROOT))],
    }
    OUT.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result["metrics"], indent=2))


if __name__ == "__main__":
    main()
