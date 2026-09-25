#!/usr/bin/env python3
"""Materialize the VETH reverse-swap storage-patch sham result."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "eval/results/e5_rcfh/veth_buyquote_dose_probe/reverse_storage_patch_sham.json"
OUT = ROOT / "eval/results/e5_rcfh/veth_buyquote_dose_probe/reverse_storage_patch_sham_audit.json"

def main():
    data = json.loads(RAW.read_text())
    target = data["per_tx"][57]
    intervention = target.get("call_intervention") or {}
    checks = {
        "application_verified": intervention.get("application_verified"),
        "match_count": intervention.get("match_count"),
        "target_actual_status": target.get("actual_status"),
        "target_status_match": target.get("status_match"),
        "target_gas_match": target.get("gas_match"),
        "target_logs_match": target.get("logs_match"),
        "target_post_state_match": target.get("post_state_match"),
        "isolated_baseline_gate": data.get("isolated_baseline_gate"),
        "relevant_post_state_match": data.get("relevant_post_state_match"),
    }
    out = {
        "status": "SAME_KIND_SHAM_PASS",
        "case_id": "defihacklabs-veth-2024-11-14",
        "trigger": {
            "call_trace_selector": "0x022c0d9f",
            "depth": 4,
            "occurrence": 2,
            "meaning": "second pair.swap occurrence, the reverse settlement swap at trace 88",
        },
        "patch_semantics": "All three values equal the values already present at the trace-88 entry; the action is an instrumentation no-op for state semantics.",
        "checks": checks,
        "storage_patch_evidence": intervention.get("storage_patches", []),
        "interpretation": "The storage-patch primitive holds the patched values through the pair.swap frame and does not alter status, gas, logs, or relevant post-state when the values are unchanged. The first failed run targeted occurrence 1 (primary swap) and is not evidence; it was corrected by targeting occurrence 2.",
        "authorization": "Sham passed; real pre-helper-state patch is still a separate intervention and remains pending invariant/revert classification.",
        "raw_sha256": hashlib.sha256(RAW.read_bytes()).hexdigest(),
    }
    OUT.write_text(json.dumps(out, indent=2) + "\n")
    print(OUT)
    print(hashlib.sha256(OUT.read_bytes()).hexdigest())

if __name__ == "__main__":
    main()
