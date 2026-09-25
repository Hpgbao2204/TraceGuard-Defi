"""E5 replay adapter contract and code-level Gate-3 checks.

The adapter is deliberately dependency-injected: this module validates a
reviewed seam/claim pair, but does not fabricate a fork mutation or harm
vector when no replay backend is supplied.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class ReplayResult:
    execution_status: str
    harm_vector: dict | None = None
    reason: str | None = None
    trace_divergence_point: int | None = None


def gate3_target_check(seam_group: dict, claim: dict) -> ReplayResult | None:
    """Reject a seam not bound to the claimed victim/asset or harm point."""
    allowed = {str(x).lower() for x in claim.get("victim_or_asset_addresses", [])}
    callee = str(seam_group.get("callee", "")).lower()
    if allowed and callee not in allowed:
        return ReplayResult("NOT_TESTABLE", reason="TARGET_MISMATCH_CALLEE_NOT_CLAIMED_VICTIM_OR_ASSET")
    harm_index = claim.get("harm_write_trace_index")
    indices = [int(x.get("trace_index")) for x in seam_group.get("occurrences", []) if x.get("trace_index") is not None]
    if harm_index is not None and indices and min(indices) > int(harm_index):
        return ReplayResult("NOT_TESTABLE", reason="SEAM_DOWNSTREAM_OF_HARM_WRITE")
    if seam_group.get("match_count") not in (None, 1):
        return ReplayResult("NOT_TESTABLE", reason="SEAM_MATCH_COUNT_NOT_UNIQUE")
    return None


def run_tier1(case: dict, seam_group: dict, claim: dict, *, replay_backend=None) -> ReplayResult:
    blocked = gate3_target_check(seam_group, claim)
    if blocked:
        return blocked
    if replay_backend is None:
        return ReplayResult("NOT_TESTABLE", reason="REPLAY_BACKEND_NOT_SUPPLIED")
    return replay_backend(case, seam_group, claim)
