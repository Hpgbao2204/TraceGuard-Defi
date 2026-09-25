"""Materialize Stage 1 vNext gate evidence without touching frozen P7 artifacts."""
from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "eval" / "vnext"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        return "unknown"


def main() -> int:
    rows = [json.loads(line) for line in (ROOT / "corpus/incidents.jsonl").read_text().splitlines() if line.strip()]
    attacks = [r for r in rows if r.get("class") == "attack"]
    verified = [r for r in attacks if r.get("verified") == "onchain"]
    hard_scope = json.loads((ROOT / "eval/results/hard_negative_queue_scope_audit.json").read_text())
    hard_manifest = json.loads((ROOT / "eval/results/hard_negative_review_queue_v2_manifest.json").read_text())
    promotion_paths = sorted((ROOT / "eval/vnext/recovery").glob("positive_provenance_promotions_v*.jsonl"))
    promotions = [json.loads(x) for p in promotion_paths for x in p.read_text().splitlines() if x.strip()]
    p7_metrics = ROOT / "eval/results/paper_metrics.json"
    p7_split = ROOT / "eval/results/runs/p7-canonical-split-20260912-r1/split_manifest.json"

    gate_a = {
        "schema_version": 1, "spec_version": "vnext-gates-v1", "gate_id": "A",
        "status": "FAIL" if len(verified) < 100 else "CONDITIONAL" if len(verified) < 150 else "PASS",
        "criteria": {"pass_min": 150, "conditional_min": 100, "fit": 90, "calibration": 30, "test": 30},
        "counts": {"raw_incidents": len(rows), "attack_rows": len(attacks), "verified_attack_incidents": len(verified),
                   "recovery_promoted_attack_incidents": len({x.get('incident_id') for x in promotions}),
                   "verified_attack_incidents_including_recovery_promotions": len(verified) + len({x.get('incident_id') for x in promotions}),
                   "verified_attack_transactions": sum(len(r.get("tx_hashes", [])) for r in verified),
                   "verified_usable_attacks_current_registry": len(verified),
                   "blocked_attack_rows": len(attacks) - len(verified),
                   "canonical_tx_hashes": sum(len(r.get("tx_hashes", [])) for r in verified)},
        "chains": dict(Counter(r.get("chain", "") for r in verified)),
        "source_counts": dict(Counter(r.get("source", "") for r in verified)),
        "rejection_reason_counts": {
            "NOT_CURRENTLY_ONCHAIN_VERIFIED": sum(1 for r in attacks if r.get("verified") != "onchain" and r.get("tx_hashes")),
            "NO_TX_HASH": sum(1 for r in attacks if not r.get("tx_hashes")),
        },
        "reason": "Current registry has only on-chain-verified rows; blocked rows are not promoted.",
        "outputs": ["corpus/incidents.jsonl"],
    }
    gate_b = {
        "schema_version": 1, "spec_version": "vnext-gates-v1", "gate_id": "B",
        "status": "FAIL", "stress_test_enabled": False, "hard_negative_training_enabled": False,
        "pilot_n": 0, "verified_hard_negatives": 0,
        "counts": {"legacy_queue_rows": hard_scope["queue_rows"], "same_protocol_true": hard_scope["observed"]["protocol_match_counts"].get("true", 0),
                   "within_window_true": hard_scope["observed"]["within_window_true"],
                   "v2_candidate_count": hard_manifest["candidate_count"],
                   "v2_benchmark_eligible": hard_manifest["benchmark_eligible"]},
        "reason": "No 30-case vNext blinded pilot or verified hard-negative registry exists; legacy queues are not promotable.",
        "legacy_scope_audit": "eval/results/hard_negative_queue_scope_audit.json",
    }
    gate_c = {
        "schema_version": 1, "spec_version": "vnext-gates-v1", "gate_id": "C",
        "status": "CONDITIONAL",
        "standard_grouped_split_valid": True,
        "chronological_split_valid": True,
        "family_holdout_enabled": False,
        "protocol_holdout_enabled": False,
        "hard_negative_holdout_enabled": False,
        "grouped_evidence": "eval/results/runs/leakage-audit-20260914-r1/leakage_audit_manifest.json",
        "reason": "Existing grouped/chronological evidence is usable diagnostically; vNext verified corpus and optional strata are not yet frozen.",
    }
    gate_d = {
        "schema_version": 1, "spec_version": "vnext-gates-v1", "gate_id": "D", "status": "PASS",
        "protocol": "docs/vnext_statistical_protocol.md",
        "bootstrap_replicates": 2000, "confidence_level": 0.95,
        "primary_ranking_metric": "AUPRC", "primary_operating_metric": "Recall at calibration-targeted 1% FPR",
        "threshold_from_test": False, "paired_comparison": True,
    }
    gates_dir = OUT / "gates"
    dump(gates_dir / "gate_a_positive_yield.json", gate_a)
    dump(gates_dir / "gate_b_hard_negative_yield.json", gate_b)
    dump(gates_dir / "gate_c_corpus_structure.json", gate_c)
    dump(gates_dir / "gate_d_statistical_protocol.json", gate_d)
    summary = {
        "schema_version": 1, "spec_version": "vnext-gates-v1",
        "gate_a": gate_a["status"], "gate_b": gate_b["status"], "gate_c": gate_c["status"], "gate_d": gate_d["status"],
        "core_rebuild_authorized": gate_a["status"] in {"PASS", "CONDITIONAL"} and gate_c["status"] in {"PASS", "CONDITIONAL"},
        "operation_semantic_authorized": False, "hard_negative_stress_authorized": False,
        "hard_negative_training_authorized": False, "family_holdout_authorized": False, "protocol_holdout_authorized": False,
        "reason": "Gate A FAIL and Gate B FAIL; no model run authorized.",
    }
    dump(gates_dir / "gate_summary.json", summary)
    inputs = [p7_metrics, p7_split, ROOT / "corpus/incidents.jsonl", ROOT / "eval/results/hard_negative_queue_scope_audit.json", ROOT / "eval/results/hard_negative_review_queue_v2_manifest.json"]
    manifest = {
        "schema_version": 1, "spec_version": "vnext-gates-v1", "created_utc": datetime.now(timezone.utc).isoformat(),
        "source_commit": commit(), "git_dirty": True, "frozen_baseline": {"paper_metrics": sha256(p7_metrics), "p7_split": sha256(p7_split)},
        "gates": {"A": gate_a["status"], "B": gate_b["status"], "C": gate_c["status"], "D": gate_d["status"]},
        "inputs": [{"path": str(p.relative_to(ROOT)), "sha256": sha256(p)} for p in inputs],
        "environment": {"python": sys.version, "platform": platform.platform()}, "authorization": summary,
    }
    dump(OUT / "vnext_repro_manifest.json", manifest)
    checksum_lines = []
    for p in sorted(OUT.rglob("*.json")):
        checksum_lines.append(f"{sha256(p)}  {p.relative_to(ROOT)}")
    (OUT / "SHA256SUMS").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
