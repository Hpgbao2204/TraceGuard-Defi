"""Fail-closed validation of concrete JUMPI targets against frame bytecode."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def bytecode_bytes(code: str) -> bytes:
    return bytes.fromhex(code[2:] if code.startswith("0x") else code)


def opcode_map(code: str) -> dict[int, int]:
    raw = bytecode_bytes(code)
    result = {}
    pc = 0
    while pc < len(raw):
        op = raw[pc]
        result[pc] = op
        pc += 1
        if 0x60 <= op <= 0x7F:
            pc += op - 0x5F
    return result


def audit(provenance: dict) -> dict:
    frame_code = provenance.get("frame_code", {})
    rows = []
    for observation in provenance.get("observations", []):
        if observation.get("kind") != "branch_predicate":
            continue
        target = observation.get("branch_target")
        code = frame_code.get(observation.get("frame_id"))
        target_opcode = None
        target_valid = False
        if isinstance(target, int) and isinstance(code, str):
            target_opcode = opcode_map(code).get(target)
            target_valid = target_opcode == 0x5B
        rows.append({
            "observation_id": observation["observation_id"],
            "frame_id": observation.get("frame_id"),
            "pc": observation.get("pc"),
            "target": target,
            "branch_taken": observation.get("branch_taken"),
            "target_opcode": target_opcode,
            "target_validated_jumpdest": target_valid,
            "scope_status": "TARGET_VALIDATED_SCOPE_UNRESOLVED" if target_valid else "TARGET_UNVALIDATED",
        })
    return {
        "schema_version": "e5-control-scope-audit-v1",
        "branch_count": len(rows),
        "target_validated_count": sum(row["target_validated_jumpdest"] for row in rows),
        "control_scope_ready": False,
        "reason": "Bytecode target validation is not a post-dominator/control-region proof.",
        "branches": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text())
    args.output.write_text(json.dumps(audit(payload["provenance"]), indent=2) + "\n")


if __name__ == "__main__":
    main()
