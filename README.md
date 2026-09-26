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

# Figures
python -m eval.plots.fig_rq1 && python -m eval.plots.fig_rq2 && python -m eval.plots.fig_rq3 && python -m eval.plots.fig_rq4
python -m eval.plots.fig_rq4_mainnet
```

Timing results depend on the machine; small differences from the paper are expected.

## Tests

```bash
python -m pytest -q                                  # tests that need local data skip without it
go -C tools/geth-replay test -mod=vendor ./...
```

## License

MIT; see [LICENSE](LICENSE).
