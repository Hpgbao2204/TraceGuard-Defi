# TraceGuard causal-analysis reference bundle

This bundle contains the current causal-analysis implementation and evidence
boundary for external review.

## Current architecture

```text
authenticated historical replay
        -> raw CALL/STATICCALL extraction
        -> candidate filtering/ranking (diagnostic)
        -> human semantic binding
        -> same-kind sham
        -> claim-bound counterfactual replay
        -> comparability gate
        -> bounded causal verdict or abstention
```

The current research contribution is validity-gated, transaction-scoped causal
testing. The SCM and EVM graph are infrastructure; automatic root-cause
discovery is not claimed.

## Current evidence

- MuReDistribution: `SUPPORTED_NECESSITY_BLOCKING`, attack outcome removed.
- SummerFi: `NAV_MECHANISM=SUPPORTED_ROOT`; final extraction not testable due
  to the attacker's self-guard.
- VETH: inconclusive before harm because downstream repayment fails.
- OnyxDAO: not observable under the current harm-boundary evidence.
- Alkimiya: arithmetic/call candidate needs opcode telemetry; E5 replay remains
  non-comparable.

## Important limitations

- The v2 candidate pilot had residual manually injected mechanism nodes and is
  not a blind scientific benchmark.
- The v3 raw-trace extractor removes those nodes, but currently achieves only
  diagnostic ranking and needs opcode/value provenance.
- All 19 available fixed-20 B2 artifacts are `OPCODE_TAIL_ONLY`; zero have
  full `structLogs`, stack, `frameId`, and `storageContextAddress`.
- The hard-negative material has 80 groups / 160 transactions but no
  authenticated B2 candidate traces in this workspace.

## Recommended next step

Acquire full provenance-preserving opcode traces for the four frozen harm cases,
then connect `dynamic_provenance.py` to harm-anchored backward slicing. Do not
infer storage ownership from depth or call target, and do not promote ranking
to a causal verdict without replay/sham/comparability gates.

The included results are diagnostic artifacts, not a new paper benchmark.
