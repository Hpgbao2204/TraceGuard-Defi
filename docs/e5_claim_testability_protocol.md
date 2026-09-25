# E5 Claim-Testability / Falsification Protocol

This document defines the evaluation question separately from the A/B/C
implementation roadmap.

## Claim unit

A supplied root-cause claim is not treated as ground truth. It is normalized
to:

```text
mechanism
enabling_factors
vulnerable_boundary
causal_variable
protected_target
target_effect
candidate_intervention
provenance
```

Factor labels are enablers unless the source explicitly identifies them as the
causal mechanism.

## Testability gates

```text
LOCALIZABLE
  -> OBSERVABLE_TARGET_EFFECT
  -> INTERVENABLE
  -> STATE_CONSISTENT
  -> EXECUTION_COMPARABLE
  -> OUTCOME_OBSERVABLE
  -> claim result
```

Failure at any gate emits a typed `NOT_TESTABLE_*` result. No USD valuation is
required when a claim-specific committed target effect is available, but a
mere mutation, trace change, or revert is not an outcome.

## Verdicts

- `SUPPORTED`: the target effect disappears under a valid, comparable
  intervention and same-kind sham passes.
- `CONTRADICTED`: execution is comparable and the target effect persists.
- `PARTIAL_EFFECT`: the target effect changes but is not eliminated.
- `NOT_TESTABLE_*`: a required localization, state, execution, or observation
  gate is unavailable.

## Dose-response overlay

Dose-response is an extension of a claim that has passed the binary validity
gates. Each dose records `(execution_status, target_effect)`. A revert has no
target-effect value; it is a feasible-region boundary observation only.

## Current evidence boundary

The Alkimiya A5 probe demonstrates that state-consistency can pass while real
counterfactual execution remains non-comparable. VETH dose-response V2 shows
that packed reserve decoding alone does not establish a valid AMM intervention;
all five doses reverted before target-effect observation. These are bounded
testability findings, not causal verdicts.
