"""Deterministic, fail-closed normalization for independent state diffs.

This module does not acquire RPC data or fill missing values.  It only turns a
validated stateDiff object into the canonical relevant-state representation.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


def _hex(value: Any) -> str:
    if not isinstance(value, str) or not value.startswith("0x"):
        raise ValueError("stateDiff value must be 0x-prefixed hex")
    return "0x" + value[2:].lower().zfill(64)


def _to(value: Any, baseline: Any = None) -> Any:
    if value == "=":
        if baseline is None:
            raise ValueError("unchanged stateDiff marker requires independent baseline state")
        return baseline
    if value == "-":
        raise ValueError("deleted stateDiff marker has no post-state value")
    if isinstance(value, Mapping) and "*" in value:
        value = value["*"]
    if isinstance(value, Mapping) and "+" in value:
        value = value["+"]
    if isinstance(value, Mapping) and "to" in value:
        return value["to"]
    if isinstance(value, str) and value.startswith("0x"):
        return value
    raise ValueError("stateDiff entry lacks a post-state value")


def normalize_relevant_state(state_diff: Mapping[str, Any], required: Mapping[str, Any],
                             baseline: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Extract required post-state cells; missing cells fail closed."""
    out: dict[str, Any] = {}
    for raw_address, spec in required.items():
        address = str(raw_address).lower()
        baseline_account = next((v for k, v in (baseline or {}).items()
                                 if str(k).lower() == address), {})
        if not isinstance(baseline_account, Mapping):
            baseline_account = {}
        source = next((v for k, v in state_diff.items() if str(k).lower() == address), None)
        if not isinstance(source, Mapping):
            raise ValueError(f"required account missing from independent stateDiff: {address}")
        item: dict[str, Any] = {}
        for field in ("balance", "nonce", "code_hash"):
            if field in spec:
                if field not in source:
                    raise ValueError(f"required {field} missing for {address}")
                before = baseline_account
                if source[field] == "=" and field not in before:
                    raise ValueError(f"independent baseline missing {field} for {address}")
                item[field] = _to(source[field], before.get(field))
        storage: dict[str, str] = {}
        for raw_slot in spec.get("storage", {}):
            slot = _hex(raw_slot)
            entries = source.get("storage", {})
            entry = next((v for k, v in entries.items() if _hex(k) == slot), None)
            if entry is None:
                raise ValueError(f"required storage slot missing: {address}:{slot}")
            before_account = baseline_account
            before_storage = before_account.get("storage", {}) if isinstance(before_account, Mapping) else {}
            before_value = next((v for k, v in before_storage.items() if _hex(k) == slot), None) if isinstance(before_storage, Mapping) else None
            if entry == "=" or (isinstance(entry, Mapping) and "=" in entry):
                if before_value is None:
                    raise ValueError(f"independent baseline missing storage: {address}:{slot}")
            storage[slot] = _hex(_to(entry, before_value))
        if storage:
            item["storage"] = dict(sorted(storage.items()))
        out[address] = item
    return dict(sorted(out.items()))


def relevant_state_hash(state: Mapping[str, Any]) -> str:
    payload = json.dumps(state, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(payload).hexdigest()
