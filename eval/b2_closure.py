"""Bounded authenticated-footprint closure for offline B2 replay.

Runtime read failures are discovery requests, never fidelity evidence.  Each
round acquires proofs for the requested cells and restarts the replay from the
resulting proof-bound state.  A non-convergent closure remains inconclusive.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from core.rpc import RpcClient
from eval.b2_proofs import acquire


def footprint_from_failures(failures: object) -> dict[str, set[str]]:
    """Parse only structured authenticated-read reasons emitted by B2."""
    result: dict[str, set[str]] = {}
    if not isinstance(failures, list):
        return result
    for raw in failures:
        if isinstance(raw, dict):
            address = raw.get("storage_context_address") or raw.get("address")
            slot = raw.get("slot")
            if isinstance(address, str) and address.startswith("0x"):
                result.setdefault(address.lower(), set())
                if isinstance(slot, str) and slot.startswith("0x"):
                    result[address.lower()].add(slot.lower())
            continue
        if not isinstance(raw, str):
            continue
        parts = raw.split(":")
        address: str | None = None
        slot: str | None = None
        if len(parts) == 5 and parts[0] in {"SLOAD", "SSTORE"} and parts[1] == "account" and parts[3] == "slot":
            address, slot = parts[2], parts[4]
        elif len(parts) == 4 and parts[0] in {"SLOAD", "SSTORE"} and parts[1] == "dynamic-unproven-slot":
            address, slot = parts[2], parts[3]
        elif len(parts) == 3 and parts[0] in {"SLOAD", "SSTORE"} and parts[1] == "account":
            address = parts[2]
        elif len(parts) == 3 and parts[0] in {"CREATE", "CREATE2"} and parts[1] == "destination-not-proof-bound":
            address = parts[2]
        elif len(parts) == 2 and parts[0] == "account":
            address = parts[1]
        if address is None:
            continue
        result.setdefault(address.lower(), set())
        if slot is not None:
            result[address.lower()].add(slot.lower())
    return result


def _merge(left: dict[str, set[str]], right: dict[str, set[str]]) -> bool:
    changed = False
    for address, slots in right.items():
        target = left.setdefault(address, set())
        before = len(target)
        target.update(slots)
        changed |= len(target) != before
    return changed


def _load_footprint(path: Path) -> dict[str, set[str]]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("closure footprint must be a JSON object")
    result: dict[str, set[str]] = {}
    for address, slots in payload.items():
        if not isinstance(address, str) or not isinstance(slots, list) or not all(isinstance(slot, str) for slot in slots):
            raise ValueError("closure footprint must map addresses to slot lists")
        result[address.lower()] = {slot.lower() for slot in slots}
    return result


def _canonical_footprint(footprint: dict[str, set[str]]) -> dict[str, list[str]]:
    return {address: sorted(slots) for address, slots in sorted(footprint.items())}


def footprint_id(context: Path, footprint: dict[str, set[str]], *,
                 chain_id: int, target_index: int) -> str:
    """Bind a footprint to the exact historical execution it describes."""
    block = json.loads((context / "block.json").read_text(encoding="utf-8"))
    ancestors = json.loads((context / "ancestors.json").read_text(encoding="utf-8"))
    if not isinstance(ancestors, list) or not ancestors:
        raise ValueError("footprint identity requires the canonical parent header")
    parent = ancestors[0]
    if not isinstance(parent, dict) or not parent.get("stateRoot"):
        raise ValueError("footprint identity requires parent stateRoot")
    identity = {
        "schema_version": 2,
        "chain_id": chain_id,
        "block_number": block.get("number"),
        "parent_block_hash": block.get("parentHash"),
        "parent_state_root": parent.get("stateRoot"),
        "state_root": block.get("stateRoot"),
        "target_index": target_index,
        "accounts_and_slots": _canonical_footprint(footprint),
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _write_footprint(path: Path, footprint: dict[str, set[str]]) -> None:
    path.write_text(json.dumps(_canonical_footprint(footprint), indent=2) + "\n",
                    encoding="utf-8")


def run_closure(context: Path, proofs: Path, output: Path, rpc: str,
                *, target_index: int, chain_id: int = 1,
                max_rounds: int = 3,
                resume_discovery: bool = False) -> dict:
    if max_rounds < 1:
        raise ValueError("max_rounds must be positive")
    canonical_proofs = (context / "prestate_proofs.json").resolve()
    if proofs.resolve() != canonical_proofs:
        raise ValueError("proofs must be context/prestate_proofs.json so closure cannot replay stale proof state")
    runner = Path(__file__).resolve().parent.parent / "tools" / "geth-replay" / "geth-replay"
    discovery_path = output.with_name(f"{output.stem}.footprint.json")
    if discovery_path.is_file() and not resume_discovery:
        raise ValueError(f"existing discovery artifact requires --resume-discovery: {discovery_path}")
    footprint = _load_footprint(discovery_path) if resume_discovery else {}
    rounds: list[dict] = []
    last_result: dict = {}
    client = RpcClient(rpc, timeout=60, attempts=2)
    for round_index in range(1, max_rounds + 1):
        round_output = output.with_name(f"{output.stem}.round-{round_index}.json")
        command = [str(runner), "--context", str(context), "--proofs", str(proofs),
                   "--chain-id", str(chain_id), "--target-index", str(target_index),
                   "--output", str(round_output), "--replay-mode", "discovery"]
        if discovery_path.is_file():
            command.extend(["--extra-footprint", str(discovery_path)])
        completed = subprocess.run(command, check=False, capture_output=True, text=True)
        if not round_output.is_file():
            raise RuntimeError(f"B2 runner did not write {round_output}: {completed.stderr[-500:]}")
        result = json.loads(round_output.read_text(encoding="utf-8"))
        last_result = result
        failures = result.get("authenticated_read_failures", [])
        structured_failures = result.get("authenticated_read_failure_details", [])
        discovered = footprint_from_failures(structured_failures)
        if not discovered:
            discovered = footprint_from_failures(failures)
        new_cells = _merge(footprint, discovered)
        rounds.append({"round": round_index,
                       "discovered": {a: sorted(s) for a, s in discovered.items()},
                       "new_cells": new_cells, "acceptance_gate": result.get("acceptance_gate", False)})
        # Discovery results are never evidence. Even a passing discovery run
        # must be repeated below with the exact final candidate footprint.
        if result.get("acceptance_gate"):
            break
        if not discovered or not new_cells:
            break
        _write_footprint(discovery_path, footprint)
        proof_result = acquire(context, client, extra_footprint=footprint)
        if not proof_result["prestate_proof_complete"]:
            break
    # The final validation pass must load exactly the candidate footprint just
    # written. It may not expand the footprint or reacquire proofs.
    _write_footprint(discovery_path, footprint)
    frozen_output = output.with_name(f"{output.stem}.frozen-validation.json")
    frozen_command = [str(runner), "--context", str(context), "--proofs", str(proofs),
                      "--chain-id", str(chain_id), "--target-index", str(target_index),
                      "--output", str(frozen_output), "--replay-mode", "frozen-validation",
                      "--extra-footprint", str(discovery_path)]
    completed = subprocess.run(frozen_command, check=False, capture_output=True, text=True)
    if frozen_output.is_file():
        frozen_result = json.loads(frozen_output.read_text(encoding="utf-8"))
    else:
        frozen_result = {"acceptance_gate": False,
                         "authenticated_read_failures": [],
                         "error": completed.stderr[-500:]}
    candidate_id = footprint_id(context, footprint, chain_id=chain_id,
                                target_index=target_index)
    manifest_path = output.with_name(f"{output.stem}.footprint.manifest.json")
    manifest_path.write_text(json.dumps({
        "schema_version": 1,
        "footprint_id": candidate_id,
        "chain_id": chain_id,
        "target_index": target_index,
        "footprint": _canonical_footprint(footprint),
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if frozen_result.get("acceptance_gate"):
        final = {"status": "ACCEPTED", "reason_code": "footprint_closed",
                 "rounds": rounds, "frozen_validation": frozen_result,
                 "accumulated_footprint": _canonical_footprint(footprint),
                 "footprint_id": candidate_id}
        output.write_text(json.dumps(final, indent=2, sort_keys=True) + "\n",
                          encoding="utf-8")
        return final
    reason_code = "context-incomplete" if frozen_result.get("authenticated_read_failures") else "replay-gate-failed"
    final = {
        "status": "INCONCLUSIVE",
        "reason_code": reason_code,
        "rounds": rounds,
        "frozen_validation": frozen_result,
        "accumulated_footprint": _canonical_footprint(footprint),
        "footprint_id": candidate_id,
    }
    output.write_text(json.dumps(final, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return final


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", type=Path, required=True)
    parser.add_argument("--proofs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rpc", required=True)
    parser.add_argument("--target-index", type=int, required=True)
    parser.add_argument("--chain-id", type=int, default=1)
    parser.add_argument("--max-rounds", type=int, default=3)
    parser.add_argument("--resume-discovery", action="store_true",
                        help="resume an explicitly exploratory discovery artifact")
    args = parser.parse_args()
    result = run_closure(args.context, args.proofs, args.output, args.rpc,
                         target_index=args.target_index, chain_id=args.chain_id,
                         max_rounds=args.max_rounds,
                         resume_discovery=args.resume_discovery)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "ACCEPTED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
