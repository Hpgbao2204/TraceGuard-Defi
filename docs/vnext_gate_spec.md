# Stage 1 vNext Gate Specification

Spec version: `vnext-gates-v1`  
Status: preregistration draft for execution  
Scope: Stage 1 only

## Purpose

Evaluate data yield, hard-negative yield, corpus structure, and statistical protocol before rebuilding Stage 1. Frozen P7 artifacts remain read-only.

```text
Gate A → Gate B → Gate C → Gate D
→ vNext corpus
→ same Call + Token + Economic baseline
→ robustness evaluation
→ optional Operation Semantic view
```

## Invariants

- Binary target only: `attack=1`, `benign=0`.
- `negative_tier` is metadata, never a third class.
- No model, feature schema, threshold, or headline metric changes before all gates.
- vNext writes only under `corpus/vnext/`, `eval/vnext/`, and `docs/vnext_*.md`.
- Missing evidence is fail-closed.
- Frozen P7 references are read-only: `eval/results/paper_metrics.json` and the corrected P7 run lineage.

## Gate A — Positive Corpus Yield

Use transaction-level, verified, deduplicated attacks from declared public sources. Record source revision, retrieval time, license/provenance, incident ID, chain, transaction hash, and evidence pointer. Reject or retain in a rejection log candidates that are unresolved, duplicates, non-exploit transactions, out of scope, unsupported, or conflicting.

- `PASS`: ≥150 usable attacks and grouped allocation supports 90 fit, 30 calibration, 30 test positives.
- `CONDITIONAL`: 100–149, or grouping prevents target allocation.
- `FAIL`: <100 or untrustworthy provenance/deduplication.

Outputs: `corpus/vnext/positive_registry.jsonl`, `corpus/vnext/positive_rejections.jsonl`, `eval/vnext/gates/gate_a_positive_yield.json`.

## Gate B — Hard-Negative Yield

Use contract-local historical mining as the primary acquisition path. First freeze a `contract_anchor_registry` from verified attacks (exact vulnerable contract, proxy/implementation, protocol family, relevant function, attack block). Acquire only pre-attack historical transactions interacting with an exact anchor or explicitly related protocol contract, then apply a frozen attack-shape filter without using model scores. Run exactly 30 blinded pilot candidates. Reviewer labels are `VERIFIED_BENIGN`, `KNOWN_MALICIOUS`, `PROTOCOL_MISUSE`, `WHITEHAT_RESCUE`, or `UNCERTAIN`; only `VERIFIED_BENIGN` counts. Exact-contract relation is the strongest tier; same-protocol relation must be explicitly evidenced and is not inferred from co-membership. Historical traffic is not presumed benign.

- Stress capability: ≥50 verified hard negatives.
- Training capability: ≥200, with ≥100 completely unseen holdout examples.
- `PASS`: both capabilities.
- `CONDITIONAL`: stress only.
- `FAIL`: fewer than 50 attainable.

Report yield and 95% Wilson interval. Do not call N=50 a precise 1% FPR estimate.

Outputs: `corpus/vnext/contract_anchor_registry.jsonl`, `corpus/vnext/hard_negative_candidates.jsonl`, `corpus/vnext/hard_negative_pilot_reviews.jsonl`, `corpus/vnext/hard_negative_registry.jsonl`, `eval/vnext/gates/gate_b_hard_negative_yield.json`.

## Gate C — Corpus Structure

Audit family, protocol, time, source, chain, incident ID, duplicates, and negative tier. Freeze grouped and chronological manifests with exact IDs, grouping key, and seed. Enable family holdout only with ≥4 families each having `n_attack ≥ 10`. Enable protocol holdout only with ≥5 protocols each having `n_attack ≥ 10`. Hard-negative holdout requires Gate B.

- `PASS`: grouped and chronological splits valid, leakage audit passes, and at least one optional axis enabled.
- `CONDITIONAL`: grouped and chronological valid, optional axes insufficient.
- `FAIL`: leakage prevention, chronological holdout, or deterministic deduplication fails.

Outputs: `eval/vnext/gates/gate_c_corpus_structure.json`, `eval/vnext/splits/vnext_split_plan.json`, and exact fit/calibration/test ID files.

## Gate D — Paired Statistical Protocol

Freeze before inspecting comparisons: same test IDs, grouping, seeds, calibration/test separation, metric definitions, threshold rule, resampling units, 2,000 bootstrap replicates, 95% confidence, and bootstrap seed. Primary metrics: AUPRC and recall at calibration-targeted 1% FPR. Secondary: precision, realized FPR, coverage, and runtime. Accuracy is descriptive only.

Allowed sequence: B0 (`Call + Token + Economic`), Gate-C robustness, then optional S1 (`+ Operation Semantic`), then optional H1 hard-negative-aware training.

Gate D has no conditional state. Missing any frozen protocol field means `FAIL`.

Output: `docs/vnext_statistical_protocol.md`, `eval/vnext/gates/gate_d_statistical_protocol.json`.

## Authorization and provenance

Core rebuild requires A ∈ {PASS, CONDITIONAL}, B evaluated, C ∈ {PASS, CONDITIONAL}, and D = PASS. Optional experiments require explicit capability flags; missing evidence never authorizes execution.

Create `eval/vnext/vnext_repro_manifest.json`, `eval/vnext/gates/gate_summary.json`, and `eval/vnext/SHA256SUMS`. Hash raw inputs, normalized registries, split manifests, selection scripts, protocols, and final artifacts with SHA-256. Frozen artifacts are never overwritten. Final paper-eligible runs require a clean worktree.

Forbidden before evidence: improved-performance, hard-negative-robustness, protocol-generalization, sparse-family-generalization, population-level 1% FPR guarantee, or Operation Semantic benefit claims.
