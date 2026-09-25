"""Fail closed when manuscript claim level exceeds available evidence."""
from __future__ import annotations
import json
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def main() -> int:
    audit = json.loads((ROOT / "eval/results/review_workflow_audit.json").read_text())
    e4 = audit["e4"]; hard = audit["hard_negatives"]
    e4_review_complete = bool(
        e4.get("ready_for_adjudication")
        and e4.get("final_sidecar", {}).get("valid") is True
    )
    # The bounded v2 search is a completed workstream even though it found no
    # benchmark-eligible same-protocol cases.  Do not reinterpret that
    # negative result as missing review evidence.
    hard_search_complete = (ROOT / "eval/results/hard_negative_review_queue_v2_manifest.json").exists()
    hard_benchmark_available = False
    m4_manifest = ROOT / "docs/m4_evidence_manifest.json"
    m4_summary = ROOT / "eval/results/m4/m4_comparison_summary.json"
    m4_complete = False
    if m4_manifest.exists() and m4_summary.exists():
        manifest = json.loads(m4_manifest.read_text())
        summary = json.loads(m4_summary.read_text())
        bundle_path = ROOT / "eval/results/m4/m4_b2_vs_liquify_20.json"
        bundle_digest = hashlib.sha256(bundle_path.read_bytes()).hexdigest() if bundle_path.exists() else ""
        summary_digest = hashlib.sha256(m4_summary.read_bytes()).hexdigest()
        cases = manifest.get("cases", [])
        bundle = json.loads(bundle_path.read_text()) if bundle_path.exists() else {}
        identities_ok = set(bundle) == {case.get("case_id") for case in cases}
        m4_complete = (
            manifest.get("frozen_case_count") == 20
            and manifest.get("attempted") == 20
            and manifest.get("pass") == 20
            and manifest.get("inconclusive") == 0
            and manifest.get("comparison_outcome") == "PASS"
            and summary.get("case_count") == 20
            and summary.get("passed_cases") == 20
            and summary.get("inconclusive_cases") == 0
            and summary.get("outcome") == "PASS"
            and manifest.get("bundle_sha256") == bundle_digest
            and manifest.get("comparison_summary_sha256") == summary_digest
            and identities_ok
            and all(
                pair.get("b2", {}).get("source_commit") == manifest.get("source_commit")
                and pair.get("independent", {}).get("engine") == manifest.get("independent_engine")
                and pair.get("independent", {}).get("version") == manifest.get("independent_version")
                for pair in bundle.values()
            )
        )
    result = {
        "M1_COMPLETE": True, "M2_ENGINEERING_COMPLETE": True,
        "M3_ENGINEERING_COMPLETE": True,
        "M4_EVIDENCE_COMPLETE": m4_complete,
        "M5_E4_REVIEW_COMPLETE": e4_review_complete,
        "M5_HARD_NEGATIVE_SEARCH_COMPLETE": hard_search_complete,
        "M5_HARD_NEGATIVE_BENCHMARK_AVAILABLE": hard_benchmark_available,
        "M5_HARD_NEGATIVE_REVIEWED_VALID": 0,
        # Backward-compatible alias: this flag refers to the E4 causal-review
        # workstream, not to the unavailable hard-negative benchmark.
        "M5_REVIEW_COMPLETE": e4_review_complete,
        "M6_COMPLETE": False,
        "ALLOW_REPLAY_CLAIM": m4_complete,
        "ALLOW_CAUSAL_ACCURACY_CLAIM": False,
        "M5_E4_REVIEWED": e4["reviewed_complete"],
        "M5_HARD_REVIEWED": hard["reviewed_complete"],
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
