"""Validate the public-RCA verification pilot's evidence bindings."""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "eval/results/e5_rcfh/public_rca_claim_verification_manifest_v1.json"
OUT = ROOT / "eval/results/e5_rcfh/public_rca_claim_verification_audit_v1.json"

def main() -> int:
    manifest = json.loads(MANIFEST.read_text())
    rows = []
    for case in manifest["cases"]:
        checks = {}
        for name, rel in case["evidence"].items():
            path = ROOT / rel
            checks[name] = {"path": rel, "exists": path.is_file()}
        complete = all(x["exists"] for x in checks.values())
        rows.append({
            "case_id": case["case_id"],
            "expected_class": case["expected_class"],
            "evidence_complete": complete,
            "checks": checks,
            "public_claim_is_hypothesis_only": True,
            "promoted_by_this_audit": False,
        })
    result = {
        "schema_version": 1,
        "status": "PASS" if all(r["evidence_complete"] for r in rows) else "INCOMPLETE_EVIDENCE_BINDING",
        "scope": manifest["scope"],
        "reference_leakage": False,
        "verdicts_derived": False,
        "rows": rows,
        "note": "This audit checks artifact binding only; it does not convert public RCA into causal evidence.",
    }
    OUT.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1

if __name__ == "__main__":
    raise SystemExit(main())
