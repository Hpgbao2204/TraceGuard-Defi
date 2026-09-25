"""Pure Outcome Guard policy for the proposal-v2 protocol.

The policy consumes already-verified evidence.  It deliberately has no RPC,
filesystem, subprocess, environment or reporting dependency.  Legacy verdict
strings are not interpreted here; callers must select the protocol explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ExecutionState(str, Enum):
    EXECUTED = "EXECUTED"
    REVERTED = "REVERTED"
    UNOBSERVED = "UNOBSERVED"


class HarmState(str, Enum):
    HARMFUL = "HARMFUL"
    AT_OR_BELOW_THRESHOLD = "AT_OR_BELOW_THRESHOLD"
    UNKNOWN = "UNKNOWN"
    NOT_HARMFUL = "NOT_HARMFUL"


class Verdict(str, Enum):
    CAUSE = "CAUSE"
    NO_EFFECT = "NO_EFFECT"
    INCONCLUSIVE = "INCONCLUSIVE"


class CausalEvidence(str, Enum):
    TRUE = "true"
    FALSE = "false"


@dataclass(frozen=True)
class OutcomeDecision:
    """Decision and the first failed gate, suitable for artifact serialization."""

    verdict: Verdict
    causal_evidence: CausalEvidence
    reason_code: str
    defense_blocked: bool = False


@dataclass(frozen=True)
class OutcomePolicy:
    """Apply the frozen protocol-v2 removal-intervention rules."""

    protocol_version: str = "counterfactual-validity-v2"

    def decide(
        self,
        *,
        baseline_execution: ExecutionState,
        mutation_execution: ExecutionState,
        baseline_harm: HarmState,
        mutation_harm: HarmState,
        fidelity_pass: bool,
        controls_pass: bool,
        intervention_valid: bool,
        harm_comparable: bool = False,
        defense_blocked: bool = False,
    ) -> OutcomeDecision:
        """Return a fail-closed verdict without inferring missing evidence.

        ``defense_blocked`` is diagnostic only.  A guard revert therefore
        remains INCONCLUSIVE with false causal evidence, even when the guard
        selector and frame were independently verified by the caller.
        """
        if baseline_execution is not ExecutionState.EXECUTED:
            return self._inconclusive("baseline-not-executed", defense_blocked)
        if not fidelity_pass:
            return self._inconclusive("baseline-fidelity-failed", defense_blocked)
        if baseline_harm is not HarmState.HARMFUL:
            return self._inconclusive("baseline-harm-not-established", defense_blocked)
        if not harm_comparable:
            return self._inconclusive("harm-specification-not-comparable", defense_blocked)
        if not controls_pass:
            return self._inconclusive("controls-failed", defense_blocked)
        if not intervention_valid:
            return self._inconclusive("intervention-invalid", defense_blocked)
        if mutation_execution is ExecutionState.UNOBSERVED:
            return self._inconclusive("mutation-unobserved", defense_blocked)
        if mutation_execution is ExecutionState.REVERTED:
            return self._inconclusive("mutation-reverted", defense_blocked)
        if mutation_harm is HarmState.UNKNOWN:
            return self._inconclusive("mutation-harm-unknown", defense_blocked)
        if mutation_harm is HarmState.AT_OR_BELOW_THRESHOLD:
            return OutcomeDecision(
                Verdict.CAUSE,
                CausalEvidence.TRUE,
                "executed-valid-harm-removed",
                defense_blocked,
            )
        if mutation_harm is HarmState.HARMFUL:
            return OutcomeDecision(
                Verdict.NO_EFFECT,
                CausalEvidence.FALSE,
                "executed-valid-harm-remains",
                defense_blocked,
            )
        return self._inconclusive("mutation-harm-not-comparable", defense_blocked)

    @staticmethod
    def _inconclusive(reason_code: str, defense_blocked: bool) -> OutcomeDecision:
        return OutcomeDecision(
            Verdict.INCONCLUSIVE,
            CausalEvidence.FALSE,
            reason_code,
            defense_blocked,
        )
