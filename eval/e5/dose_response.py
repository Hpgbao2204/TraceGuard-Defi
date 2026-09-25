"""Pure dose-response bookkeeping for E5 oracle/AMM sweeps."""
from __future__ import annotations

from decimal import Decimal


def build_dose_grid(manipulated: int, truthful: int, points: int = 5) -> list[int]:
    """Return deterministic inclusive linear doses; no replay is performed."""
    if points < 2:
        raise ValueError("points must be >= 2")
    if manipulated == truthful:
        return [int(manipulated)] * points
    out = []
    for i in range(points):
        value = Decimal(manipulated) + (Decimal(truthful - manipulated) * i / (points - 1))
        out.append(int(value))
    return out


def classify_doses(observations: list[dict]) -> dict:
    """Summarize executed doses without treating a revert as zero harm."""
    executed = [x for x in observations if x.get("execution") == "EXECUTED"]
    reverted = [x for x in observations if x.get("execution") == "REVERTED"]
    comparable = [x for x in executed if x.get("harm") is not None]
    if not comparable:
        return {"status": "NOT_TESTABLE", "reason": "NO_COMPARABLE_EXECUTED_DOSE", "executed": len(executed), "reverted": len(reverted)}
    values = [int(x["harm"]) for x in comparable]
    return {
        "status": "OBSERVED",
        "executed": len(executed),
        "reverted": len(reverted),
        "harm_min": min(values),
        "harm_max": max(values),
        "threshold_value": next((x.get("dose") for x in sorted(comparable, key=lambda y: y.get("dose", 0)) if int(x["harm"]) == 0), None),
        "revert_is_null_harm": True,
    }
