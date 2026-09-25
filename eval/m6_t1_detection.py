"""Compatibility wrapper for the single Harm-v2 T1 raw-delta engine.

The previous implementation had a second token/address interpretation and
could silently disagree with T0.  Keep this import path for callers, but make
all T1 detection go through ``m6_harm_v2.t1``.
"""
from eval.m6_harm_v2 import t1
from eval.m6_harm_boundary_register import validate_boundary


def detect_t1(flows, boundary, attacker_addresses=(), complete=True):
    if not isinstance(boundary, dict):
        return {"status": "UNKNOWN", "tier": "T1", "reason": "boundary_missing"}
    # Preserve the legacy adapter contract for rows without Harm-v2 policy
    # metadata; enforce strict validation once a v2 status is declared.
    if "status" in boundary:
        valid, reason = validate_boundary(boundary)
        if not valid:
            return {"status": "UNKNOWN", "tier": "T1", "reason": reason}
    observation = t1(
        flows,
        boundary.get("protected_entities", []),
        attacker_addresses=attacker_addresses or boundary.get("attacker_addresses", []),
        boundary_id=boundary.get("boundary_id", "frozen-protected-registry-v1"),
        complete=complete,
    )
    return observation.json()
