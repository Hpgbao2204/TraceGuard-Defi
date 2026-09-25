# M4 Differential Validation

Status: COMPLETE / frozen evidence

M4 validates the B2/Geth replay substrate against independent execution
evidence. It does not infer independent evidence and does not issue causal
verdicts. The frozen sample must contain 10–20 predeclared cases and bind each
case to the source commit, context manifest, B2 evidence, independent source,
engine, and version.

Each case is comparable only when both sides provide typed values for:

- receipt status;
- gas used;
- logs hash;
- relevant post-state hash.

Missing, malformed, or mismatched evidence is `INCONCLUSIVE`. An equal empty
value is not evidence unless it was explicitly materialized by the evidence
producer. The comparator lives in `eval/m4_differential.py` and is covered by
`tests/test_m4_differential.py`.

Current status:

- manifest validator: implemented;
- deterministic evidence hashing: implemented;
- fail-closed comparator: implemented;
- manifest-level provenance checker and comparison summary: implemented;
- SHA-256 digest format and distinct-producer checks: implemented;
- frozen 20-case selection manifest: supplied in `docs/m4_frozen_case_manifest.json`;
- differential cases run: 20/20;
- exact differential matches: 20/20;
- causal verdicts: none.

The manifest-level entry point is `compare_manifest_evidence()`. It requires
case identity, B2 source-commit binding, context-manifest binding, and
independent-source identity before comparing typed execution evidence. Both
logs and relevant-state fields must be materialized SHA-256 digests, and the
two declared producers must be distinct. The next safe action is to prepare
acquire independent execution evidence for the frozen case manifest. This
remains separate from human annotation and reviewer adjudication. No existing
historical B2 or Anvil artifact is promoted as independent evidence.

`context_manifest_hash` is a lowercase SHA-256 digest of the canonical
context-manifest bytes. Producers and consumers must use the same byte-level
serialization contract. The CLI is fail-closed for automation: exit `0` only
for an overall `PASS`, exit `2` for a valid but `INCONCLUSIVE` comparison, and
exit non-zero for malformed input or execution errors.

The comparator is also bound to the repository frozen-set digest
`5db36702f741e874c208874b841cc6acb7bcb863b7a2a257926aee2f5002bd90`; a
self-declared alternative 20-case manifest is rejected.

Frozen evidence is persisted in `docs/m4_evidence_manifest.json` and
`eval/results/m4/m4_comparison_summary.json`, with implementation checkpoint
`34a1ee7`, B2/Geth source checkpoint `872658c`, and independent producer
Nethermind v1.39.3. The strict comparison result is 20/20 PASS; M4 does not
produce causal labels.
