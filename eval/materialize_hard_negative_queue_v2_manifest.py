"""Write provenance manifest for the review-only hard-negative queue v2."""
from __future__ import annotations
import hashlib, json, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "eval/results/hard_negative_review_queue_v2.csv"
LEADS = ROOT / "eval/results/hard_negative_queue_v2_leads.json"
OUT = ROOT / "eval/results/hard_negative_review_queue_v2_manifest.json"

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main() -> None:
    leads = json.loads(LEADS.read_text(encoding="utf-8"))
    rows = max(0, len(CSV.read_text(encoding="utf-8").splitlines()) - 1)
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        commit = "unknown"
    payload = {
        "schema_version": 1,
        "status": "review_only_pending_human_review",
        "generation_source_commit": commit,
        "queue": "eval/results/hard_negative_review_queue_v2.csv",
        "queue_sha256": sha(CSV),
        "source_relation_evidence": "eval/results/hard_negative_queue_v2_leads.json",
        "source_relation_evidence_sha256": sha(LEADS),
        "candidate_count": rows,
        "selection_policy": "within frozen window plus non-infrastructure exact anchor/runtime evidence; no labels inferred",
        "required_human_fields": ["same_protocol", "same_contract_family", "legitimate_mechanism", "label", "rationale", "evidence", "reviewer_note"],
        "benchmark_eligible": False,
    }
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"candidate_count": rows, "benchmark_eligible": False}))

if __name__ == "__main__":
    main()
