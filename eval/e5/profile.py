"""Pure E5 Tier-2 profiling helpers.

Replay orchestration is intentionally injected by the caller. These helpers
only classify already observed, comparable harm outcomes and therefore cannot
silently turn a missing replay into a causal result.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable


@dataclass(frozen=True)
class RestoreObservation:
    restore_set: frozenset[str]
    execution: str
    harm_removed: bool | None
    trace_divergence_point: int | None = None


def ddmin_restore(groups: Iterable[str], flips_harm_off: Callable[[frozenset[str]], bool]) -> frozenset[str]:
    """Find a 1-minimal restore set using ddmin-style set reduction."""
    current = frozenset(groups)
    if not flips_harm_off(current):
        raise ValueError("full restore set must remove harm")
    n = 2
    while current:
        parts = _split(current, min(n, len(current)))
        progress = False
        for part in parts:
            remainder = current - part
            if remainder and flips_harm_off(remainder):
                current, n, progress = remainder, max(n - 1, 2), True
                break
            if flips_harm_off(part):
                current, n, progress = part, 2, True
                break
        if not progress:
            if n >= len(current):
                break
            n = min(n * 2, len(current))
    return current


def _split(items: frozenset[str], n: int) -> list[frozenset[str]]:
    ordered = sorted(items)
    return [frozenset(ordered[i::n]) for i in range(n) if ordered[i::n]]


def classify_profile(claimed_group: str, observations: list[RestoreObservation]) -> dict:
    """Classify a profile while preserving execution/masking evidence."""
    if not observations:
        return {"outcome": "NOT_TESTABLE", "reason": "NO_REPLAY_OBSERVATIONS"}
    full = next((x for x in observations if not x.restore_set), None)
    if full is None or full.harm_removed is not True:
        return {"outcome": "NO_TESTABLE_MECHANISM_EXPLAINS_HARM", "full_restore": full.execution if full else None}
    single = [x for x in observations if len(x.restore_set) == 1 and x.harm_removed is True]
    if len(single) == 1:
        group = next(iter(single[0].restore_set))
        return {"outcome": "ALTERNATIVE_CAUSE_IDENTIFIED" if group != claimed_group else "CLAIMED_CAUSE_SUPPORTED", "identified_group": group, "masks": []}
    if len(single) > 1:
        masks = {next(iter(x.restore_set)): x.trace_divergence_point for x in single if x.trace_divergence_point is not None}
        return {"outcome": "CONJUNCTIVE_OR_SERIAL_CANDIDATES", "groups": sorted(masks), "trace_divergence_points": masks}
    return {"outcome": "CONJUNCTIVE_SET_REQUIRES_DDMIN", "full_restore": True}
