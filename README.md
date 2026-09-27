# TraceGuard-DeFi

Validity-aware screening and counterfactual replay for DeFi exploits and ordering attacks.

TraceGuard-DeFi asks a question about the victim rather than the attacker's script: *would the victim have lost the
same assets had it observed a neutral value, or not been preceded by a suspected transaction?* It answers on
EIP-1186-authenticated Ethereum state and abstains whenever the counterfactual is not comparable.

- **Stage 1** ranks transactions with a calibrated three-view screener (call structure, token flow, economic actions)
  under a frozen false-positive-rate budget.
- **Stage 2** replays candidates in a patched go-ethereum engine on proof-verified state and applies read-site-scoped
  value interventions (exploits) or transaction-drop interventions (sandwiches), with revert-origin attribution,
  guard typing, and frame-local replay. Every verdict (`CAUSE`, `CAUSE_BLOCKED`, `PARTIAL`, `NO_EFFECT`,
  `INCONCLUSIVE(reason)`) is fail-closed.

## Layout

| Path | Contents |
|---|---|
| `core/` | Stage 1 views, fusion, calibration; trace parsing; harm accounting |
| `tools/geth-replay/` | Go replay engine (proof verification, scoping, `-drop-tx`, `-lean`); `cmd/framelocal/` is the frame-local runner |
| `eval/` | Experiments: grouped screening (`e1_grouped_*`, `e3_grouped_v2`), `rq2/`, `rq3/`, `mev_sim/` (RQ4), `plots/` |
| `corpus/` | Incident loaders and labeling scripts |
| `tests/`, `eval/tests/` | pytest suites |

`tools/geth-replay/vendor/` contains a patched go-ethereum v1.17.5; always build with `-mod=vendor`.

## Setup

```bash
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt eth-abi eth-utils pycryptodome pytest
go -C tools/geth-replay build -mod=vendor -o ../../.cache/geth-replay .
go -C tools/geth-replay build -mod=vendor -o ../../.cache/framelocal ./cmd/framelocal
```

RQ4 additionally needs [Foundry](https://book.getfoundry.sh/) (`anvil`). Datasets, replay contexts, and trace caches
are distributed separately and are expected under `eval/results/` and `eval/artifacts/`.

## Reproducing the evaluation

```bash
# RQ1: block-grouped screening split, model, temporal/held-family folds, near-negative cohort
python -m eval.e1_grouped_v2 --run-id split --seed 42
python -m eval.e1_grouped_train_v2 --split-dir eval/results/runs/split --run-id model
python -m eval.e1_grouped_robustness_v2 --cache eval/results/e1_trace_cache.jsonl --run-id robustness
python -m eval.e3_grouped_v2 --model-run model --split-run split --run-id near-negative

# RQ2: fidelity is checked against canonical receipts; lean latency over 20 contexts x 10 runs
python -m eval.rq2.latency --exe .cache/geth-replay --repeats 10

# RQ1 revision analyses: view ablation, baselines, bootstrap CIs, paired grouped/leaky splits, calibration,
# out-of-fold scores for the fixed-20 queue
python -m eval.revision.stage1 --seeds 50

# RQ3: frozen fixed-20 queue (rules v2 and v3) and the Euler and Alkimiya positive controls
python -m eval.rq3.final_table --exe .cache/framelocal --factors eval/rq3/fixed20_factors.json --out .cache/rq3_final_v2
python -m eval.rq3.final_table --exe .cache/framelocal --factors eval/rq3/fixed20_factors_v3.json --out .cache/rq3_final_v3
python -m eval.rq3.positive_controls --exe .cache/framelocal

# RQ3: mechanical boundary amendment (published next to the frozen manifest), rules re-derived on it
python -m eval.rq3.boundary_amendment      # needs an archive RPC and a trace RPC (.env)
python -m eval.rq3.discover_factors --exe .cache/framelocal --manifest eval/rq3/fixed20_cases_amended.json --rule v2 --factors eval/rq3/fixed20_factors_amended_v2.json
python -m eval.rq3.discover_factors --exe .cache/framelocal --manifest eval/rq3/fixed20_cases_amended.json --rule v3 --v2 eval/rq3/fixed20_factors_amended_v2.json --factors eval/rq3/fixed20_factors_amended_v3.json
python -m eval.rq3.final_table --exe .cache/framelocal --manifest eval/rq3/fixed20_cases_amended.json --factors eval/rq3/fixed20_factors_amended_v2.json --out .cache/rq3_final_amended_v2

# RQ3: root-cause-matched guard restorations (eval/rq3/guards/: sources, expected reverts, runtime hashes)
python -m eval.rq3.guard_restoration build     # needs solc 0.8.24 at .cache/solc/solc-0.8.24.exe
python -m eval.rq3.guard_restoration prepare   # adds the shadow address's non-existence proof (archive RPC)
python -m eval.rq3.guard_restoration run --exe .cache/framelocal

# RQ4: builder simulation on anvil, five seeds
for s in 1 2 3 4 5; do python -m eval.mev_sim.run --slots 200 --seed $s --out .cache/mev_sim/seed$s.json; done

# RQ4 on mainnet: weak sandwich labels, proof-bound contexts, and drop/placebo tests on the Go engine
python -m eval.revision.mainnet_sandwich scan --start 22100000 --blocks 400 --max 40
python -m eval.revision.mainnet_sandwich acquire     # a public dRPC trace endpoint works for prestateTracer
python -m eval.revision.mainnet_sandwich run --exe .cache/geth-replay

# Review revisions: block-conformal threshold, tolerance sensitivity, BlockScan on the same split,
# heuristic-negative mainnet cohort, paired/temporal Stage 1 checks
python -m eval.revision.threshold
python -m eval.revision.tolerance sim && python -m eval.revision.tolerance analyze
python -m eval.revision.blockscan prepare && python -m eval.revision.blockscan score && python -m eval.revision.blockscan evaluate
python -m eval.revision.mainnet_benign scan && python -m eval.revision.mainnet_benign acquire && \
  python -m eval.revision.mainnet_benign run --exe .cache/geth-replay && python -m eval.revision.mainnet_benign audit
python -m eval.revision.stage1_checks

# Figures
python -m eval.plots.fig_rq1 && python -m eval.plots.fig_rq2 && python -m eval.plots.fig_rq3 && python -m eval.plots.fig_rq4
python -m eval.plots.fig_rq4_mainnet
```

Timing results depend on the machine; small differences from the paper are expected.

The data behind every table and figure can be packaged with `python -m tools.build_dataset_release`, which writes
`dist/TraceGuard-DeFi_dataset_v1.zip` (datasheet, checksums, provider URLs and local paths removed, proofs kept).

## Stage 1 specification

The three views are fixed functions of the call trace (`core/views.py`); only the fusion is fitted.

| View | Score in [0, 1] |
|---|---|
| call structure | `0.35 z(log10 calls; log10 20, 0.30) + 0.20 z(depth; 5, 2.5) + 0.30 z(log10(1 + shallow-large-out frames); 0.7, 0.5) + 0.15 z(fan-out skew; 4, 6)`, with `z(x; m, s) = 1 / (1 + exp(-(x - m) / s))`; a shallow-large-out frame sits at depth <= 1 and has a subtree of at least 12 calls and 6 levels |
| token flow | `sigmoid(-0.5 + 1.5 log10(1 + src_excess) + 1.2 log10(1 + flow_excess) + 0.8 log10(1 + evt_excess))`: excess distinct sources into one (account, token), excess transfers into one (account, token), and transfer events beyond two |
| economic actions | `0.2 x` the number of signals among flash loan, oracle read, price deviation (two oracle reads, or one with a swap), zero `amountOutMin`, origin return imbalance, and a privileged call with a large transfer |
| state delta | not observed in the trace cache; constant 0 |

Fusion: `p(T) = sigmoid((w0 + sum_v w_v s_v) / theta)`, L2-regularized logistic regression (lambda = 1, seed 42)
on the fit partition and temperature scaling on the calibration partition (`core/fusion.py`). On the frozen
block-grouped split the fitted model is `w0 = -7.94`, `w_call = 5.13`, `w_token = 4.80`, `w_econ = 2.00`
(temperature folded in), `tau_1% = 0.128`; `python -m eval.revision.stage1` reproduces it and prints the weights.

## Replay semantics referenced by the paper

- Boundary amendment (RQ3): the rule, as pseudocode, is the docstring of `eval/rq3/boundary_amendment.py`.
- Value interventions (`tools/geth-replay/cmd/framelocal`): an intervened call by V is answered by a stub, so the
  callee does not run; the observed value and `v0` come from STATICCALLs on copies of the current state and of
  S0. A site whose call attempts a state write at any depth is not admissible: it runs unchanged and the run is
  INCONCLUSIVE (`site_not_read_only`).
- Ordering confound J(D) (`tools/geth-replay`, `-drop-tx`): an intermediate transaction is unchanged only if its
  status, gas, logs, and state diff (the items it writes and the amount of each change, compared with its diffMode
  prestateTracer row) match the observed order (`state_changed` otherwise). The simulator uses the same
  definition through anvil's prestateTracer (`eval/mev_sim/chain.py`).

## Tests

```bash
python -m pytest -q                                  # tests that need local data skip without it
go -C tools/geth-replay test -mod=vendor ./...
```

## License

MIT; see [LICENSE](LICENSE).
