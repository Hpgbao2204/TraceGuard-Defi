"""Alkimiya arithmetic counterfactual via historical code state override.

This is intentionally a narrow probe.  It replaces only the historical
SilicaPools runtime code at the exact target address.  It never rewrites
calldata, stack values, storage, or provider bytecode.  A patched runtime is
an explicit preregistered input; absence or ABI/provenance mismatch is a hard
blocked result.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

TARGET = "0xf3f84ce038442ae4c4dcb6a8ca8bacd7f28c9bde"
SELECTOR = "0x71e109d4"
ROOT = Path(__file__).resolve().parent.parent


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_runtime(path: Path) -> str:
    text = path.read_text(encoding="utf-8").strip()
    if text.startswith("0x"):
        runtime = text
    else:
        obj = json.loads(text)
        runtime = obj.get("deployedBytecode") or obj.get("runtime") or obj.get("bytecode")
    if not isinstance(runtime, str) or not runtime.startswith("0x"):
        raise ValueError("patched artifact has no 0x-prefixed runtime bytecode")
    if len(runtime) <= 2 or len(runtime[2:]) % 2:
        raise ValueError("patched runtime is empty or malformed")
    return runtime.lower()


def build_override(runtime: str) -> dict:
    return {TARGET: {"code": runtime}}


def preflight(patch_path: Path | None, expected_sha256: str | None) -> dict:
    base = {
        "target_address": TARGET,
        "function_selector": SELECTOR,
        "intervention": "historical_runtime_code_override_only",
        "calldata_or_stack_patch": False,
        "storage_patch": False,
        "global_bytecode_patch": False,
    }
    if patch_path is None or not patch_path.exists():
        return {**base, "status": "BLOCKED_MISSING_PREREGISTERED_PATCH_BYTECODE",
                "reason_code": "missing_preregistered_runtime"}
    try:
        runtime = load_runtime(patch_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {**base, "status": "BLOCKED_INVALID_PATCH_BYTECODE",
                "reason_code": str(exc)}
    digest = sha256(patch_path)
    if expected_sha256 and digest != expected_sha256:
        return {**base, "status": "BLOCKED_PATCH_HASH_MISMATCH",
                "reason_code": "preregistered_hash_mismatch",
                "observed_sha256": digest, "expected_sha256": expected_sha256}
    return {**base, "status": "READY_FOR_RPC_STATE_OVERRIDE",
            "patch_artifact": str(patch_path), "patch_sha256": digest,
            "state_override": build_override(runtime)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--patch", type=Path)
    ap.add_argument("--expected-sha256")
    ap.add_argument("--out", type=Path,
                    default=ROOT / "eval/results/m6_alkimiya_patched_code_preflight.json")
    args = ap.parse_args()
    result = preflight(args.patch, args.expected_sha256)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "READY_FOR_RPC_STATE_OVERRIDE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
