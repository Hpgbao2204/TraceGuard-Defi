"""Pre-register and audit a supplementary operator-positive M6 set.

This is an offline selection audit only. It never runs mutations and never
selects cases because a mutation happened to pass.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_jsonl(path: Path) -> dict[str, dict]:
    return {row["case_id"]: row for row in
            (json.loads(line) for line in path.read_text().splitlines() if line.strip())}


def audit(fixed: Path, sidecar: Path, harm: Path, scope: Path, out: Path) -> dict:
    cases = json.loads(fixed.read_text())["cases"]
    adjudicated = load_jsonl(sidecar)
    harm_data = json.loads(harm.read_text())["cases"]
    scope_rows = {row["case_id"]: row for row in json.loads(scope.read_text())["cases"]}
    rows = []
    for case in cases:
        cid = case["case_id"]
        review = adjudicated.get(cid, {})
        factors = review.get("root_cause_gt") or []
        subtype = scope_rows.get(cid, {}).get("mechanism_subtype")
        harm_status = harm_data.get(cid, {}).get("status")
        eligible = (set(factors) & {"f_fl", "f_orc"} and
                    ("f_orc" not in factors or subtype == "f_orc_external") and
                    harm_status == "MEASURABLE")
        rows.append({"case_id": cid, "included": bool(eligible),
                     "reason": "included" if eligible else
                     "fixed-20 does not satisfy supplementary inclusion criteria",
                     "ground_truth_factors": factors,
                     "mechanism_subtype": subtype,
                     "harm_status": harm_status})
    result = {
        "schema_version": 1,
        "purpose": "supplementary operator-positive selection audit; no replay run",
        "selection_rule": [
            "adjudicated factor is f_fl or external-feed f_orc",
            "harm status is MEASURABLE",
            "selection is independent of mutation outcome",
            "fixed-20 membership is not changed",
        ],
        "source_hashes": {"fixed": sha256(fixed), "sidecar": sha256(sidecar),
                          "harm": sha256(harm), "scope": sha256(scope)},
        "cases": rows,
        "included_count": sum(row["included"] for row in rows),
        "status": "NO_ELIGIBLE_CASES_IN_FIXED20" if not any(row["included"] for row in rows)
                  else "CANDIDATES_REQUIRE_SEPARATE_FREEZE",
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("eval/results/m6_supplementary_operator_positive_audit.json"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    result = audit(root / "docs/m4_frozen_case_manifest.json",
                   root / "corpus/annotations/adjudication/e4_adjudication_completed_reviewer_c.jsonl",
                   root / "eval/results/m6_harm_spec_v2.json",
                   root / "eval/results/m6_operator_scope_matrix.json", root / args.out)
    print(json.dumps({"status": result["status"], "included_count": result["included_count"], "out": str(args.out)}, indent=2))
