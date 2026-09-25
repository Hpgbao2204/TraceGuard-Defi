"""Claim-level falsification labels and dose-response observations for E4."""
from dataclasses import dataclass
from enum import Enum
from typing import Any


class FalsificationLabel(str, Enum):
    NECESSITY_SUPPORTED = "NECESSITY_SUPPORTED"
    NECESSITY_SUPPORTED_BLOCKING = "NECESSITY_SUPPORTED_BLOCKING"
    NECESSITY_REFUTED = "NECESSITY_REFUTED"
    PARTIAL_EFFECT = "PARTIAL_EFFECT"
    NOT_TESTABLE = "NOT_TESTABLE"


@dataclass(frozen=True)
class NecessityClaim:
    """A falsifiable claim, not an unqualified root-cause label."""

    transaction_id: str
    context_id: str
    mechanism_id: str
    harm_target_id: str
    statement: str


@dataclass(frozen=True)
class DoseObservation:
    """One preregistered intervention dose and its two-part outcome Y(x)."""

    dose_id: str
    parameter: str
    value: str
    execution_status: str
    comparability_status: str
    harm_vector: dict[str, Any] | None
    reason_code: str | None = None

    @property
    def y(self) -> dict[str, Any]:
        return {
            "E": {
                "execution_status": self.execution_status,
                "comparability_status": self.comparability_status,
            },
            "H": self.harm_vector,
        }


def classify_dose_response(observations: list[DoseObservation]) -> str:
    """Return a descriptive response class without treating revert as zero harm.

    This is intentionally not a causal verdict.  It distinguishes an observed
    executable response from a feasibility boundary and leaves the final
    claim-level adjudication to the frozen intervention protocol.
    """
    executed = [x for x in observations if x.execution_status == "EXECUTED" and x.harm_vector is not None]
    reverted = [x for x in observations if x.execution_status == "REVERTED"]
    if not executed:
        return "NO_EXECUTED_DOSES"
    if reverted and executed:
        return "RESPONSE_WITH_FEASIBILITY_BOUNDARY"
    return "EXECUTED_RESPONSE"
