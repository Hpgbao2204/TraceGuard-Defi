# E4 falsification protocol

## Claim unit

E4 does not take an unqualified label such as “oracle manipulation is the root
cause”. It takes a context-bound claim:

> Mechanism `M` was necessary for harm `H` in historical transaction `T` under
> proof-bound context `C`.

The claim freezes the transaction, context, mechanism seam, protected target,
observation scope and intervention footprint independently of the replay
outcome.

## Adjudication labels

- `NECESSITY_SUPPORTED`: valid executed counterfactual removes the frozen
  target effect.
- `NECESSITY_SUPPORTED_BLOCKING`: a valid blocking intervention satisfies the
  full blocking contract and atomically prevents the target execution.
- `NECESSITY_REFUTED`: valid counterfactual executes and the target effect
  remains.
- `PARTIAL_EFFECT`: the intervention executes and changes the target effect
  without removing it, or a dose-response threshold is observed.
- `NOT_TESTABLE`: seam, victim boundary, state observation, or comparable
  intervention cannot be established.

`REVERTED` is an execution observation, never a zero-harm value. It can only
support `NECESSITY_SUPPORTED_BLOCKING` when the separately frozen blocking
validity contract passes.

## Dose-response observation

For a preregistered dose `x`, record:

\[
Y(x) = (E(x), H(x))
\]

where `E(x)` contains execution and comparability status, and `H(x)` is a
HarmVector only when the execution is comparable. A revert has
`E=REVERTED` and `H=null`; it is not encoded as `H=0`.

The sweep must be defined before replay and must lie on an explicitly declared
intervention manifold preserving the required protocol invariants. A response
curve may show a feasibility boundary, a partial effect, or a threshold where
harm disappears, but does not by itself replace victim-bound intervention
validation.

## Scope of the current v4 result

The fixed-20 v4 artifacts provide the execution-context and abstention
infrastructure. The reviewed causal denominator is currently zero. AMM
blocking candidates are preserved as diagnostic evidence, not promoted to
causal labels. Future corpus audits should map existing RCA claims into this
claim unit and report `SUPPORTED`, `REFUTED`, `PARTIAL_EFFECT`, or
`NOT_TESTABLE` without treating reproduction/profit as necessity evidence.
