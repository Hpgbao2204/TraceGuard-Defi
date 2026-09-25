# TraceGuard E5 SCM/provenance evidence bundle

Generated: 2026-09-20

This bundle documents the completed bounded engineering plan in
`.ai/plans/e5-causal-scm.md`. It is evidence for authenticated provenance,
dependency slicing, and fail-closed diagnostics. It is **not** a causal
verdict release.

## Included evidence

- Geth telemetry implementation and the Python provenance/slicing engines.
- Focused tests for shadow stacks, return-data lineage, storage last-writer
  tracking, harm binding, and control candidates.
- MuRe, VETH, and SummerFi v7 provenance/control artifacts.
- Persisted opcode sidecars needed to reproduce the three provenance runs.
- MuRe harm binding and cross-frame ERC-1271 dependency audit.
- Plan, completion report, current state, and dated engineering journal.

## Main results

- MuRe: `HARM_NODE_BOUND`; dependency/control path recovered for
  ERC-1271 selector `0x1626ba7e`; `reference_leakage=false`; causal verdict
  remains null.
- VETH and SummerFi: provenance regenerated with zero shadow mismatches and
  zero unverified values. SummerFi is explicitly bounded by nine bootstrapped
  suffix frames.
- Bounded control diagnostics remain fail-closed. They do not establish
  control-scope proof or causal necessity.

## Reproduction

From the repository root:

```bash
python3 -m pytest tests/test_dynamic_provenance.py \
  tests/test_mure_control_candidate.py tests/test_harm_sink_binding.py -q
GOCACHE=/tmp/traceguard-gocache go test ./...
```

The complete root suite was verified as `491 passed, 7 skipped`; the skips are
Anvil-readiness skips. The raw RPC URLs in legacy artifacts were redacted
before packaging. No RPC credential is included in this bundle.

## Scope boundary

The bundle intentionally does not claim automatic root-cause discovery,
full static control coverage, independent harm discovery, or comparable
counterfactual replay. Those remain follow-on causal-release gates.
