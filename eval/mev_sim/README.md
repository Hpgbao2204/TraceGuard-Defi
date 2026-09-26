# M3: builder-side sandwich prevention, end-to-end simulation

A local anvil chain (no fork, no RPC key), a seeded mempool with users, benign searchers and
sandwich bots, and a simulated builder that runs layer 1 and layer 2 before admitting each bundle.
Every builder mode faces the same order flow; labels are known because we generate them.

## Run

```bash
# once: foundry for anvil (https://book.getfoundry.sh/getting-started/installation)
curl -L https://foundry.paradigm.xyz | bash && foundryup
pip install eth-abi eth-utils eth-account pycryptodome requests pytest

# Windows without WSL: unzip foundry_stable_win32_amd64.zip from
# https://github.com/foundry-rs/foundry/releases and put anvil.exe on PATH (or set ANVIL=C:\path\anvil.exe)

python -m eval.mev_sim.run --slots 200 --seed 7     # all six modes, ~2 min
# layer 2 on the paper's replay engine (build it first: cd tools/geth-replay && go build -mod=vendor)
python -m eval.mev_sim.run --slots 200 --seed 7 --l2-engine geth
python -m pytest -q tests/test_mev_sim.py           # the anvil test skips if anvil is missing
```

Output: `eval/mev_sim/results.json` (git-ignored): config, per-mode summary, and every bundle decision.
`contracts/artifacts.json` is committed, so solc is only needed after editing `contracts/src/`
(`SOLC=/path/to/solc-0.8.24 python -m eval.mev_sim.build_contracts`).

## World

- Tokens A, B, C. Pools P1 and P2 trade A/B (two venues, so backrun arbitrage exists), P3 trades B/C.
  `SimPair` is a constant-product pair with Uniswap V2 swap semantics (0.3% fee, k-check); it is
  written for the simulation, not the canonical UniswapV2Pair bytecode. No V3 pool yet.
- `SimRouter` (path swaps, add/remove liquidity) and `SimAggregator` (split routes, different calldata).
- Each transaction is its own anvil block; a slot is the range of blocks the builder emits. Gas price
  is zero and bids are abstract numbers in token-A units.

## Order flow per slot (`agents.py`)

- Users: Poisson(4) swaps, single-hop on P1 or P2 or two-hop A→B→C / C→B→A, size 0.2–2% of the
  input reserve, slippage 0.5–3%, via router or aggregator.
- Sandwich bot (45% of user swaps, when profitable): largest front-run the victim's slippage allows,
  profit-maximising, bid = 80% of expected profit. Variants: `classic`, `split` (2–4 front-runs),
  `addr_swap` (front-run pays out to a second address that back-runs), `aggregator`,
  `multipool` (two-hop victim, attacker trades the whole route), `decoy` (proceeds hop through a fresh
  account between front-run and victim, so dropping the front-run changes an intermediate tx).
- Benign searchers: backrun arbitrage P1↔P2 on every user swap that moves P1/P2; shape lookalikes on
  30% of the remaining P1 swaps: `jit` (add liquidity before, remove after), `mm_reverse`
  (opposite-direction trade before, reverse after), `xpool` (same-direction trade on P2 before, reverse after).

## Builder (`builder.py`) and filters (`detection.py`)

Bundles are taken in bid order; a bundle whose txs are already in the block is skipped (`conflict`),
one with any reverting tx is dropped (`invalid`). Remaining user txs are appended in arrival order.

| mode | rule |
|---|---|
| `none` | include every valid bundle |
| `heur_strict` | mev-inspect shape: same sender swaps the victim's pool in the victim's direction before and the opposite direction after |
| `heur_naive` | any front-victim-back shape: same sender before and after, the tx before moves a token the victim trades |
| `l1_only` | exclude what layer 1 flags |
| `tg_open` / `tg_closed` | layer 1, then layer 2; CAUSE → EXCLUDE, NO_EFFECT → INCLUDE, INCONCLUSIVE → DEFAULT, which the builder resolves to include / exclude |

- Layer 1 reads the bundle's own simulation logs: flag if a searcher tx before the victim changed a
  pool the victim swaps on. Those txs are the drop set.
- Layer 2 drops them, re-simulates the rest of the bundle on the same block prefix, and compares the
  victim's net inflow of its output token. `CAUSE` if the victim gets at least 10 bps more
  (`--rel-threshold`), `NO_EFFECT` otherwise. `INCONCLUSIVE(ordering_confound)` when an intermediate tx between the
  drop set and the victim changes status or logs (`intermediate_changed`) or the victim itself reverts
  without the drop set (`victim_reverted`); `INCONCLUSIVE(no_victim_output)` when no victim output can
  be identified. INCONCLUSIVE maps to DEFAULT, never directly to EXCLUDE; metrics report EXCLUDE-on-CAUSE
  and DEFAULT separately.
- Ground truth harm is computed separately with the x*y=k model on the reserves read before the bundle.

## Layer 2 engines (`--l2-engine`, `geth_bridge.py`)

- `anvil` (default, what PR #3 reported): the drop-and-resimulate step above runs as anvil
  snapshot/execute/revert, and the comparison is Python code in `detection.layer2`.
- `geth` (the paper's Stage 2): the builder mines the flagged bundle as **one** anvil block on the
  current prefix (transactions signed with the simulation keys), exports it as a B2 context
  (header, prefix+victim transactions, receipts, prestate/diff/call traces, EIP-1186 proofs against
  the parent state root, 256 ancestor headers), then runs `geth-replay -chain-id 31337 -lean
  -target-index <victim>` twice: without intervention, where `acceptance_gate` (the RQ2 fidelity
  gate) must hold, and with `-drop-tx <layer-1 suspects>` (M1). Fail-closed, confounds and
  comparability come from the engine's `ordering_intervention` report; the victim's output is read
  from the engine's target logs. INCONCLUSIVE reasons: `replay_gate_failed`, `fail_closed`,
  `ordering_confound` (`victim_reverted`, `intermediate_changed`; the engine also counts gas-only
  changes), `incomparable`, `engine_error`, `no_victim_output`. The mined block is reverted afterwards,
  so the chain evolves exactly as in the `anvil` engine. Each record keeps the anvil verdict too
  (`anvil_verdict`, `anvil_harm`), and the run prints fidelity-gate passes and engine agreement.
- Chain profile `31337` in `tools/geth-replay/chainconfig.go` is anvil's `--hardfork shanghai`
  (all forks and the merge at genesis, no Cancun system calls); it is marked experimental and is
  used only here. `MEVSIM_KEEP_CONTEXTS=1` keeps the exported contexts in the temp directory.
- Layer 1 is a bundle-level screen, not the three-view Stage 1 screener of RQ1: that screener is
  trained on exploit incidents and is not applied to bundles.

## Metrics (`metrics.py`)

Per mode: sandwich bundles blocked / evaluated (overall and per variant), benign bundles blocked /
evaluated (per kind), sandwiches landed, realized victim harm and harm avoided versus `none`,
layer-2 verdict counts, layer-2 harm vs ground truth, filter latency per slot (p50/p95/max) and the
share of slots within 12 s and 500 ms. Rates carry Wilson 95% intervals.

## Limits to state when citing

- Latency is anvil JSON-RPC time (snapshot, execute, revert), an upper bound for an in-process builder.
  With `--l2-engine geth` the per-bundle `geth_timing` holds the engine's `timing_ms` (`target_evm`,
  `evm_replay`) on these small blocks; `l2_ms` then also includes mining, context export and two
  process starts, so it is not a builder latency either. The latency claim stays with RQ2 (W1).
- Lookalike bids are set just above the backrun bid so the builder evaluates them; this measures
  false-positive decisions, not the economics of those strategies.
- Bundles are sized on the slot-start state, so many go stale and revert (`invalid`) when other bundles
  land first; counts of evaluated bundles differ across modes for that reason.
- Harm below the threshold (a dust sandwich) is let through by design.
