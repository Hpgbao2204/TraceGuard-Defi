"""Boundary adapter from E4 evidence rows to the protocol-v2 domain policy.

The adapter performs only field translation.  It does not fetch evidence or
reinterpret legacy verdicts, so old run directories remain immutable.
"""

from __future__ import annotations

from typing import Any

from core.domain.policy import (
    ExecutionState,
    HarmState,
    OutcomeDecision,
    OutcomePolicy,
)

# Only sources produced by a protected-objective ledger can support a causal
# comparison.  Public incident loss and attacker value are reference or
# diagnostic data, not measured counterfactual harm.
PROTECTED_HARM_LEDGER_SOURCES = frozenset({
    "receipt_transfer_ledger",
    "pool_balance_delta",
    "euler_bad_debt_delta",
    "replayed_counterfactual_delta",
    "intervention_validated_harm",
})

# M2's release contract is intentionally narrower than the experimental
# mutation catalogue.  Other operators remain useful diagnostics, but cannot
# enter the causal numerator until their semantics are frozen and evidenced.
OFFICIAL_M2_OPERATORS = frozenset({"f_fl", "f_orc"})


def _operator_factor(row: dict[str, Any]) -> str:
    """Read the normalized factor, tolerating legacy rows at the boundary."""
    explicit = str(row.get("candidate_factor") or "")
    if explicit:
        return explicit
    mutation = str(row.get("mutation") or "")
    return next((factor for factor in ("f_fl", "f_orc")
                 if mutation.startswith(factor)), "")

def _detection_comparable(baseline: dict[str, Any], mutation: dict[str, Any]) -> bool:
    """Require identical raw-harm semantics; valuation is deliberately ignored."""
    fields = ("detection_spec_id", "harm_tier", "boundary_id",
              "hard_asset_registry", "observation_scope")
    present = [f for f in fields if baseline.get(f) not in (None, "")
               or mutation.get(f) not in (None, "")]
    if not present:
        return True  # preserve legacy rows without v2 metadata
    return all(baseline.get(f) not in (None, "")
               and baseline.get(f) == mutation.get(f) for f in present)


def _controls_harm_equivalent(controls: list[dict[str, Any]], baseline: dict[str, Any] | None) -> bool:
    """Require positive/sham controls to describe the same measured harm.

    Legacy rows sometimes omit control metadata entirely.  In that case this
    helper preserves the historical control gate.  Once either control row
    carries harm metadata, missing or mismatching structure fails closed.
    """
    positive = next((r for r in controls if r.get("control_type") == "positive"), None)
    sham = next((r for r in controls if r.get("control_type") == "sham"), None)
    if not positive or not sham:
        return False
    fields = ("harm_spec_id", "harm_source", "harm_source_mutated")
    has_metadata = any(any(r.get(f) not in (None, "") for f in fields)
                       for r in (positive, sham, baseline or {}))
    if not has_metadata:
        return True
    reference = baseline or positive
    spec = str(reference.get("harm_spec_id") or "")
    source = str(reference.get("harm_source") or "")
    sham_source = str(sham.get("harm_source_mutated") or sham.get("harm_source") or "")
    return bool(spec and source in PROTECTED_HARM_LEDGER_SOURCES
                and str(sham.get("harm_spec_id") or "") == spec
                and sham_source == source)


def _execution(value: Any) -> ExecutionState:
    if value in ("EXECUTED", "EXECUTED_UNKNOWN", "EXECUTED_HARM", "EXECUTED_NO_HARM", True, 1):
        return ExecutionState.EXECUTED
    if value in ("REVERTED", "REVERT", False, 0):
        return ExecutionState.REVERTED
    return ExecutionState.UNOBSERVED


def _harm(value: Any) -> HarmState:
    if value in ("HARM", "HARMFUL", True, 1):
        return HarmState.HARMFUL
    if value in ("NO_HARM", "AT_OR_BELOW_THRESHOLD", "NOT_HARMFUL", False, 0):
        return HarmState.AT_OR_BELOW_THRESHOLD
    return HarmState.UNKNOWN


def decide_row(row: dict[str, Any], *, policy: OutcomePolicy | None = None) -> OutcomeDecision:
    """Decide one protocol-v2 row from already collected evidence fields.

    Missing booleans fail closed.  ``execution_preserving`` is deliberately
    not accepted as an alias for intervention validity.
    """
    selected = policy or OutcomePolicy()
    return selected.decide(
        baseline_execution=_execution(row.get("baseline_outcome", row.get("baseline_status"))),
        mutation_execution=_execution(row.get("mutation_outcome", row.get("outcome"))),
        baseline_harm=_harm(row.get("baseline_harm")),
        mutation_harm=_harm(row.get("mutated_harm", row.get("harm_Sm"))),
        fidelity_pass=row.get("fidelity_pass") is True,
        controls_pass=row.get("controls_pass") is True,
        intervention_valid=row.get("intervention_valid") is True,
        harm_comparable=row.get("harm_comparable", False) is True,
        defense_blocked=row.get("defense_blocked") is True,
    )


def apply_policy_rows(rows: list[dict[str, Any]], *, policy: OutcomePolicy | None = None) -> list[dict[str, Any]]:
    """Apply protocol-v2 decisions without mutating the legacy evidence."""
    selected = policy or OutcomePolicy()
    baseline = next((row for row in rows if row.get("mutation") == "fidelity"), None)
    controls = [row for row in rows if row.get("control_type")]
    controls_pass = (
        {"positive", "sham"}.issubset({row.get("control_type") for row in controls})
        and all(row.get("control_pass") is True for row in controls)
        and _controls_harm_equivalent(controls, baseline)
    )
    baseline_harm = None
    baseline_spec = ""
    if baseline and baseline.get("harm_source") in PROTECTED_HARM_LEDGER_SOURCES:
        baseline_harm = baseline.get("harm_S")
        baseline_spec = str(baseline.get("harm_spec_id") or "")
    output: list[dict[str, Any]] = []
    for source in rows:
        row = dict(source)
        row["protocol_version"] = "outcome-policy-v2"
        row["controls_pass"] = controls_pass
        if source.get("mutation") == "fidelity":
            output.append(row)
            continue
        # Controls are evidence about the experiment, never interventions.
        # Keep their pass/fail result visible while excluding them from the
        # causal verdict and numerator.
        if source.get("control_type") in {"positive", "sham"}:
            row["legacy_verdict"] = source.get("verdict", "")
            row["verdict"] = "CONTROL_PASS" if source.get("control_pass") is True else "CONTROL_FAIL"
            row["cause"] = ""
            row["causal_evidence"] = False
            row["policy_reason"] = "control-row-excluded-from-causal-verdict"
            output.append(row)
            continue
        if _operator_factor(source) not in OFFICIAL_M2_OPERATORS:
            row["legacy_verdict"] = source.get("verdict", "")
            row["verdict"] = "INCONCLUSIVE"
            row["cause"] = ""
            row["causal_evidence"] = False
            row["policy_reason"] = "operator-out-of-scope"
            output.append(row)
            continue
        decision = decide_row({
            "baseline_outcome": baseline.get("outcome") if baseline else None,
            "mutation_outcome": source.get("outcome"),
            "baseline_harm": baseline_harm,
            "mutated_harm": (
                None if source.get("harm_source_mutated") == "attacker_value_delta"
                else source.get("harm_Sm")
            ),
            "fidelity_pass": baseline.get("fidelity_pass") is True if baseline else False,
            "controls_pass": controls_pass,
            "intervention_valid": (source.get("intervention_valid") is True
                and source.get("mutation_application_verified") is True
                and source.get("mutation_contract_verified") is True),
            "harm_comparable": bool(
                baseline_spec
                and str(source.get("harm_spec_id") or "") == baseline_spec
                and source.get("harm_source_mutated") in PROTECTED_HARM_LEDGER_SOURCES
                and _detection_comparable(baseline or {}, source)
            ),
            "defense_blocked": source.get("defense_blocked") is True,
        }, policy=selected)
        row["legacy_verdict"] = source.get("verdict", "")
        row["verdict"] = decision.verdict.value
        row["cause"] = "1" if decision.verdict.value == "CAUSE" else ""
        row["causal_evidence"] = decision.causal_evidence.value == "true"
        row["policy_reason"] = decision.reason_code
        output.append(row)
    return output
