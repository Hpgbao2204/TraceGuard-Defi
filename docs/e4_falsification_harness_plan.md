# E4 follow-up: falsification harness for DeFi root-cause claims

## Decision

The Harm-v4 fixed-20 result is not reported as a successful causal-attribution
benchmark. The two AMM blocking candidates are retained as diagnostic
artifacts but withdrawn from the causal denominator: their target is an
automatic-complement pool address and the reserve substitution changes a
slippage precondition before harm can be observed. The current audited causal
result is therefore `0 CAUSE / 0 NOT_NECESSARY`.

## Research question

Can a published or dataset-supplied root-cause claim for a historical DeFi
incident be falsified by a proof-bound counterfactual replay, or must the
system abstain because the claim is not identifiable under the frozen
execution context?

The output vocabulary is:

- `SUPPORTED`: the declared intervention passes seam, sham, boundary,
  execution and harm-comparability gates and removes the frozen target effect.
- `CONTRADICTED`: the intervention is valid and the target effect remains.
- `NOT_TESTABLE`: the required intervention, boundary, state observation or
  execution-preserving semantics cannot be established.

These labels are claim-level and context-specific. They do not assert that a
different attack path is impossible.

## Evidence assets already available

- proof-bound B2 prestate/poststate contexts for the frozen 20;
- canonical run selection with failed-run quarantine;
- versioned hard-asset registry and raw HarmVector;
- strict caller/callee/selector/depth seam descriptors;
- same-kind sham and blocking-revert validation;
- machine-readable reason codes for non-observability and non-comparability.

## Dose-response extension

For oracle/AMM mechanisms, the next intervention is a preregistered sweep of
one semantic parameter, not a binary drop:

```text
pin level x: manipulated return -> pre-manipulation return
measure: execution status, terminal HarmVector, settlement status
```

The sweep range, points, target boundary, resolver version and stopping rule
must be frozen before replay. Reverts are recorded as feasibility boundaries,
not as `NO_HARM`. A response curve is causal evidence only when the same-kind
sham, victim-bound target and execution footprint gates pass.

## Reporting

Report separately:

1. corpus and context integrity;
2. harm observability by tier;
3. intervention identifiability and abstentions;
4. dose-response feasibility curves;
5. `SUPPORTED`, `CONTRADICTED` and `NOT_TESTABLE` outcomes.

Do not compare the detector to RCA systems by raw F1. Use the existing detector
as a screener and the proof-bound replay as an adjudicator.
