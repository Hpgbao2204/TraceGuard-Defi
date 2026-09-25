"""Pure causal verdict policy for E4.

No RPC, filesystem, subprocess, or replay dependency belongs here.  This
module preserves the current outcome-guard semantics while providing a seam
for later separation of removal and insertion-blocking policies.
"""

from __future__ import annotations

from core.outcome import Outcome


def criterion(
    outcome: str,
    *,
    baseline_harm: str = "UNKNOWN",
    mutated_harm: str = "UNKNOWN",
    observed: bool = True,
    execution_preserving: bool = False,
    behavior_changed: bool = False,
) -> str:
    """Evaluate the current removal-style E4 causal criterion.

    Reverts, transport failures, invalid interventions, and unmeasured harm
    remain inconclusive.  One mutation that fails to remove harm is not proof
    that the transaction is benign.
    """
    if not observed:
        return "INCONCLUSIVE-transport"
    if baseline_harm == "UNKNOWN":
        return "INCONCLUSIVE-harm-unmeasured"
    if baseline_harm != "HARM":
        return "INCONCLUSIVE-baseline-harm"
    if outcome == Outcome.REVERTED.value:
        return "INCONCLUSIVE-revert"
    if not execution_preserving:
        return "INCONCLUSIVE-invalid-intervention"
    if not behavior_changed:
        return "INCONCLUSIVE-no-effect"
    if mutated_harm == "NO_HARM":
        return "CAUSE"
    if mutated_harm == "HARM":
        return "NOT_NECESSARY"
    return "INCONCLUSIVE-harm-unmeasured"


def evaluate_removal_intervention(
    *,
    baseline_harm: bool | None,
    mutation_executed: bool,
    mutation_harm: bool | None,
    intervention_supported: bool,
) -> str:
    """Small typed seam for removal-style policy consumers."""
    if not intervention_supported:
        return "INCONCLUSIVE"
    if baseline_harm is None:
        return "INCONCLUSIVE-harm-unmeasured"
    if not baseline_harm:
        # Necessity is only defined for an actually harmful baseline.  A
        # benign baseline cannot establish that removing the factor was
        # unnecessary; it leaves the causal question untested.
        return "INCONCLUSIVE-baseline-harm"
    if not mutation_executed:
        return "INCONCLUSIVE-revert"
    if mutation_harm is None:
        return "INCONCLUSIVE"
    return "NOT_NECESSARY" if mutation_harm else "CAUSE"


def evaluate_blocking_intervention(
    *,
    baseline_harm: bool,
    reached_check: bool,
    reverted_expected_reason: bool,
    reverted_expected_frame: bool,
    reverted_oog: bool,
) -> str:
    """Typed seam for insertion-blocking mutations such as Euler's guard."""
    if not baseline_harm:
        return "NOT_NECESSARY"
    if not reached_check:
        return "INCONCLUSIVE"
    if reverted_oog:
        return "INCONCLUSIVE-oog"
    if not (reverted_expected_reason and reverted_expected_frame):
        return "INCONCLUSIVE-revert"
    return "CAUSE-NECESSARY-blocking"


def evaluate_blocking_revert_v4(
    *,
    baseline_hard: dict,
    counterfactual_reverted: bool,
    seam_match_count: int,
    intervention_applied: bool,
    same_kind_sham_pass: bool,
    callback_postconditions_pass: bool,
    footprint_pass: bool,
    counterfactual_neg: set | None,
    target: tuple | None,
) -> str:
    """Apply the v4 blocking-revert validity contract.

    A revert is causal evidence only when every provenance and validity gate
    is independently satisfied and the frozen target negative effect is absent
    in the counterfactual vector.  This policy deliberately does not infer
    anything from a revert alone.
    """
    if not any(int(v) < 0 for v in baseline_hard.values()):
        return "INCONCLUSIVE_BASELINE_HARM"
    if not counterfactual_reverted:
        return "INCONCLUSIVE_NOT_BLOCKING"
    if seam_match_count != 1 or not intervention_applied:
        return "INCONCLUSIVE_INTERVENTION_APPLICATION"
    if not same_kind_sham_pass:
        return "INCONCLUSIVE_SHAM"
    if not callback_postconditions_pass or not footprint_pass:
        return "INCONCLUSIVE_SEMANTIC_VALIDATION"
    if counterfactual_neg is None:
        return "INCONCLUSIVE_HARM_OBSERVATION"
    if counterfactual_neg:
        return "INCONCLUSIVE_HARM_REMAINS"
    if target is None or target not in {k for k, v in baseline_hard.items() if int(v) < 0}:
        return "INCONCLUSIVE_TARGET_NOT_IN_BASELINE"
    return "CAUSE-NECESSARY-blocking"
