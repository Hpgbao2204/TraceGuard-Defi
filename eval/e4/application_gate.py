"""Validate read-back evidence of patch application, not semantic validity."""

from __future__ import annotations


def application_gate(payload: dict, requested: dict, target_index: int) -> tuple[bool, str]:
    # Production interventions are per-slot patches.  A full storage
    # replacement is too broad to establish mutation validity.
    if requested.get("state") or payload.get("target_state"):
        return False, "full-storage-override-forbidden"
    if payload.get("prestate_proof_verified") is not True:
        return False, "prestate-proof-missing"
    if payload.get("prefix_gas_match") is not True:
        return False, "prefix-fidelity-failed"
    if payload.get("target_index") != target_index:
        return False, "wrong-target-index"
    expected = {}
    if requested.get("target_data") is not None:
        expected[("data", "", "")] = requested["target_data"].lower()
    for address, code in requested.get("target_code", {}).items():
        expected[("code", address.lower(), "")] = code.lower()
    for destination, source in requested.get("target_code_copy", {}).items():
        expected[("code-copy", destination.lower(), source.lower())] = None
    for address, slots in requested.get("target_storage", {}).items():
        for slot, value in slots.items():
            expected[("storage", address.lower(), slot.lower())] = value.lower()
    evidence = payload.get("mutation_application")
    if not expected or not isinstance(evidence, list) or len(evidence) != len(expected):
        return False, "application-evidence-missing-or-extra"
    seen = set()
    changed = False
    for entry in evidence:
        if not isinstance(entry, dict):
            return False, "application-evidence-malformed"
        kind = entry.get("kind")
        if kind == "code-copy":
            key = (kind, str(entry.get("address", "")).lower(),
                   str(entry.get("source", "")).lower())
        else:
            key = (kind, str(entry.get("address", "")).lower(),
                   str(entry.get("slot", "")).lower())
        if key in seen or key not in expected:
            return False, "unexpected-patch"
        seen.add(key)
        if entry.get("target_index") != target_index or entry.get("prefix_completed") != target_index:
            return False, "wrong-application-order"
        before, after = entry.get("before"), entry.get("after")
        if not isinstance(before, str) or not isinstance(after, str):
            return False, "readback-missing"
        if kind == "code-copy":
            if not entry.get("source") or after.lower() in {"0x", "0x0"}:
                return False, "readback-mismatch"
        elif after.lower() != expected[key]:
            return False, "readback-mismatch"
        changed |= before.lower() != after.lower()
    return (True, "application-verified") if changed else (False, "mutation-no-op")
