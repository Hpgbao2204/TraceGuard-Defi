# TraceGuard-DeFi (TraFiSec)

Two-stage DeFi incident triage for an NSS 2026 submission (Springer LNCS, double-blind, 15 pages).
Stage 1 is a calibrated three-view screener; Stage 2 is proof-authenticated go-ethereum replay with
read-site-scoped interventions, revert-origin attribution and frame-local counterfactual replay.

## Layout

- `paper/` — manuscript; local-only (git-ignored) while under double-blind review.
- `core/` — Stage 1 views/fusion/screener, trace parsing, legacy Anvil fork/mutation harness, harm accounting.
- `tools/geth-replay/` — Go replay engine (EIP-1186 proof verification, scoping, revert classifier,
  frame recorder). `cmd/framelocal/` is the current frame-local runner. Build: `cd tools/geth-replay && go build -mod=vendor ./...`.
  `vendor/` holds a PATCHED go-ethereum v1.17.5 (adds `vm.CallIntervention` in `core/vm/evm.go` and
  `core/vm/instructions.go`). Always build in vendor mode; never run `go mod vendor`/`go get` over it, or the patch is lost.
- `tools/geth-replay-framelocal/` — legacy frame-local port kept for comparison; not used for RQ3.
- `eval/` — experiments: `e1_*` (Stage 1, RQ1–RQ4), `m4_independent/` (RQ5 fidelity vs Nethermind),
  `e4/` and `e5/` (Stage 2 attribution; `e5/` holds many per-case exploratory probes).
- `corpus/` — incident loaders and labeling scripts. `tests/`, `eval/tests/` — pytest suites.
- `docs/dev-notes/` — internal research notes; local-only (git-ignored).

## Data is local-only

Datasets, trace caches, replay contexts and experiment outputs are git-ignored (`data/`, `eval/results/`,
`eval/artifacts/`, `*.jsonl`, `corpus/annotations/`), as are `paper/` and `docs/dev-notes/`. The repository is public:
never commit author names, emails, local paths, RPC keys, or the manuscript. A session without the local data can edit code
but cannot rerun experiments; tests that read `eval/results/` will fail there.

## Commands (with local data present)

```bash
pip install -r requirements.txt
python -m pytest -q                              # ~1 min; test_audits claim check fails until paper numbers are final
python -m eval.e1_cli --steps train report       # Stage 1 from trace cache, ~2 s
```

## Known issues to keep in mind

- `tools/geth-replay/scoping.go` treats `balanceOf(address)` as a price selector; most scoped reads in the
  fixed-20 runs are `balanceOf`, not oracle/AMM reads.
- Frame-local mode replays the whole transaction from the start and cancels at target-frame exit. In
  `cmd/framelocal` the intervention applies only while the harm frame runs, attacker calldata/value/caller into
  the victim (target entry and nested entries) is checked against baseline, isolation uses identity stubs at the
  same read sites and compares log digests, and sham perturbs an unrelated (non-victim) price read. Only
  `cmd/framelocal` is used for RQ3 (`eval/rq3/run_fixed20.py`); the top-level `framelocal.go` and
  `tools/geth-replay-framelocal/` are legacy.
- RQ3 factors v2 (`eval/rq3/fixed20_factors.json`, frozen) pin `balanceOf` reads that include the victim's own
  balance; the six v2 CAUSE_BLOCKED cases are pinning artifacts (guard `self_balance_consistency`). v3
  (`fixed20_factors_v3.json`, `discover_factors --rule v3`) excludes them and must be committed before any run on it.
- `eval/results/e4_fixed20_smallproject/e4_rq6_evaluation.json` numbers do not reconcile with the run artifacts;
  do not cite them.
- Review revision (Sept 2026): `eval/rq3/fixed20_cases_amended.json` is the mechanical boundary amendment
  (`eval/rq3/boundary_amendment.py`); the frozen `fixed20_cases.json` stays unchanged and the paper reports both.
  Guard restorations live in `eval/rq3/guards/` (sources, expected reverts, `guards.lock.json`); commit changes
  there before `eval.rq3.guard_restoration run`. `cmd/framelocal` gained `-target-extra-gas` (counterfactual runs
  only) and the revert origin now follows only reverts re-raised unchanged (caught reverts are reported in
  `caught_victim_reverts`). Mainnet sandwich drop tests: `eval/revision/mainnet_sandwich.py`.
