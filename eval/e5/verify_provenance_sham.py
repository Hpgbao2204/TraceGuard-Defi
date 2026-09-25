"""Summarize the observation-only provenance replay against a canonical run."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


AUTHORITATIVE = (
    "all_gas_match", "all_status_match", "all_logs_match",
    "acceptance_gate", "prestate_proof_verified", "relevant_post_state_match",
)
TARGET = (
    "actual_gas", "expected_gas", "gas_match", "actual_status",
    "expected_status", "status_match", "logs_match", "post_state_match",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--canonical", type=Path, required=True)
    ap.add_argument("--telemetry", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    canonical = json.loads(args.canonical.read_text())
    telemetry = json.loads(args.telemetry.read_text())
    target_index = int(telemetry["target_index"])
    c_target = canonical["per_tx"][target_index]
    t_target = telemetry["per_tx"][target_index]
    authoritative_equal = all(
        canonical.get(key) == telemetry.get(key) for key in AUTHORITATIVE
    )
    target_equal = all(c_target.get(key) == t_target.get(key) for key in TARGET)
    events = t_target.get("opcode_telemetry", [])
    result = {
        "schema_version": "e5-provenance-observation-sham-v1",
        "case_id": "defihacklabs-muredistribution-2026-05-21",
        "target_index": target_index,
        "intervention": "none",
        "telemetry_enabled": True,
        "canonical_source_sha256": sha256(args.canonical),
        "telemetry_run_sha256": sha256(args.telemetry),
        "comparison": {
            "authoritative_top_level_fields_equal": authoritative_equal,
            "target_replay_fields_equal": target_equal,
            "canonical_acceptance_gate": canonical.get("acceptance_gate"),
            "telemetry_acceptance_gate": telemetry.get("acceptance_gate"),
        },
        "telemetry": {
            "opcode_event_count": len(events),
            "frame_ids": sorted({e.get("frame_id") for e in events if e.get("frame_id")}),
            "has_stack": any(isinstance(e.get("stack"), list) for e in events),
            "has_memory": any(bool(e.get("memory")) for e in events),
            "has_return_data": any("return_data" in e for e in events),
            "has_storage_context": any(bool(e.get("storage_context")) for e in events),
            "storage_change_count": len(t_target.get("storage_changes", [])),
        },
        "verdict": (
            "OBSERVATION_SHAM_PASS"
            if authoritative_equal and target_equal and telemetry.get("acceptance_gate")
            else "INCONCLUSIVE_REPLAY_MISMATCH"
        ),
        "limitation": "This verifies observation-only replay fidelity; it does not authorize a causal intervention or verdict.",
    }
    args.output.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
