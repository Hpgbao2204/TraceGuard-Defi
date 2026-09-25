# M1 real-context evidence

This document records the bounded replay evidence produced during M1
consolidation. It is an evidence index, not a release manifest and not a
causal verdict. The canonical matrix is summarized by
`m1_real_context_evidence_manifest.json`.

## Provenance

- Branch: `correctness/p7-clean-consolidation`
- Replay source commit: `b512c70`
- Evidence-document commit: recorded by Git after this update
- Replay engine: go-ethereum `v1.17.5`
- Context: temporary real-context acquired at block `22781962`
- Target transaction context: `0x1f15a193db3f44713d56c4be6679b194f78c2bcdd2ced5b0c7495b7406f5e87a`
- Canonical historical state: parent block (`b-1`)
- Closure bound: 3 rounds per invocation

The earlier exploratory results were superseded. This matrix was reacquired
from fresh schema-v3 contexts after the footprint merge fix and replayed with
frozen validation; no exploratory footprint was reused.

## Acceptance matrix

| Target index | Result | Interpretation |
|---:|---|---|
| 0 | `ACCEPTED` | Fresh frozen validation; all current M1 fidelity gates passed. |
| 1 | `ACCEPTED` | Fresh frozen validation; all current M1 fidelity gates passed. |
| 2 | `ACCEPTED` | Fresh frozen validation; all current M1 fidelity gates passed. |
| 28 | `ACCEPTED` | Fresh pre-Cancun frozen validation; fork rules and all gates passed. |

## Canonical-freeze recheck

All four fixed contexts were acquired into fresh temporary directories,
proofs were reacquired, and closure was run with the same three-round bound.
Result:

```text
targets 0, 1, 2, 28 = ACCEPTED
```

These results supersede the earlier exploratory runs for release or thesis
claims. The earlier rows are retained only as historical exploratory evidence.

The superseded exploratory target-2 run reported:

```text
prestate_proof_verified      = true
block_context_complete       = true
pre_execution_applied        = true
all_gas_match                = true
all_status_match             = true
all_logs_match               = true
relevant_post_state_match    = true
authenticated_read_failures  = none
proof_accounts_verified      = 42
proof_storage_cells_verified = 80
```

## Interpretation and limits

All four canonical targets reached `ACCEPTED` under the current proof-bound
fidelity gates. The matrix supports a narrow real-context positive-control
claim only; it does not support broad replay coverage, causal necessity, or
Stage 2 mutation validity.

The M1 StateDB boundary is now wired across precheck, PreExecution and EVM
execution, and the current regression suite passes. Broader footprint
convergence and differential coverage remain M4 questions.

All four fixed cases remain in the denominator. Their results must not be
converted to `ACCEPTED` by relaxing the guard or by treating missing state as
zero. Historical temporary files under `/tmp` are not release artifacts and
must be reacquired from a clean, provenance-recorded context for final studies.
