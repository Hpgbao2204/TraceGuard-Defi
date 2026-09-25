"""Materialize blinded, objective dossier data for the offline review portal."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKET = ROOT / "corpus/annotations/review_packets/e4_reviewer_a.jsonl"
OUT = ROOT / "corpus/annotations/review_bundles/display_evidence.json"
M4_BUNDLE = ROOT / "eval/results/m4/m4_b2_vs_liquify_20.json"
FORBIDDEN = {"gt_factors", "root_cause_gt", "attack_type", "blind_candidate_factors",
             "supported_from_cache", "trace_evidence", "system_verdict", "ground_truth",
             "adjudicated_result", "reviewer_votes", "cause", "no_effect", "inconclusive"}


def head() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def main() -> dict:
    rows = [json.loads(line) for line in PACKET.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != 20:
        raise ValueError(f"expected 20 E4 packets, got {len(rows)}")
    m4 = json.loads(M4_BUNDLE.read_text(encoding="utf-8")) if M4_BUNDLE.is_file() else {}
    cases = []
    for row in rows:
        comparison = m4.get(row["case_id"], {})
        b2 = comparison.get("b2", {})
        item = {
            "case_id": row["case_id"],
            "tx_hash": row["tx_hash"],
            "block": row["block"],
            "transaction_summary": {
                "status": b2.get("status", "unknown"),
                "gas_used": b2.get("gas_used", "unknown"),
            },
            "relevant_contracts": [],
            "relevant_calls": [],
            "asset_movements": [],
            "protected_harm_observations": [],
            "reported_loss": [],
            "candidate_intervention_observations": [],
            "sources": [{
                "artifact_path": "eval/results/m4/m4_b2_vs_liquify_20.json",
                "reference": f"case_id={row['case_id']}",
                "fields": ["b2.status", "b2.gas_used"],
            }],
            "availability": {
                "transaction_summary": "materialized from frozen M4 objective replay artifact",
                "contracts_calls_movements_harm": "not materialized in frozen review packet",
            },
        }
        leaked = {k.lower() for k in item} & FORBIDDEN
        if leaked:
            raise AssertionError(f"forbidden dossier keys: {sorted(leaked)}")
        cases.append(item)
    result = {
        "schema_version": 1,
        "generation_source_commit": head(),
        "source_packet_sha256": hashlib.sha256(PACKET.read_bytes()).hexdigest(),
        "case_count": len(cases),
        "cases": cases,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    print(json.dumps(main(), indent=2))
