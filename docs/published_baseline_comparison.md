# Published baseline comparison

## Candidate selected

The first external screening baseline is **BlockScan** (NeurIPS 2025).
Its public artifact provides Ethereum preprocessing, a foundation model, and
an anomaly-detection script; the README describes the required workflow as
preprocess, detect, and optionally post-analyse transactions.

Source: `https://github.com/nuwuxian/BlockScan`.

## Comparability contract

The comparison is limited to the shared Ethereum transaction subset for which
both systems can consume the same transaction identity and the baseline can
run without protocol-specific hand editing. We will report the exact subset,
training/reference data, threshold, source revision, model artifact hash, and
denominators. No result will be copied from the BlockScan paper.

TraceGuard Stage 1 remains a prioritization/ranking system. This comparison
does not evaluate M2 interventions, M3 harm, M4 replay fidelity, or causal
accuracy.

## Current status

The repository does not yet contain the BlockScan model/data artifact or a
port adapter. Therefore no baseline metric has been materialized and no
superiority claim is permitted. The next implementation step is an offline
adapter/provenance manifest; if the required model/data cannot be obtained or
the input modality cannot be aligned fairly, the comparison remains
`INCONCLUSIVE` with the incompatibility recorded.
