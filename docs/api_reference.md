# TraFiSec: API Reference

## 1. Core Python Module (`core`)

### `core.replay.Replayer`
High-performance Ethereum transaction replayer using direct Anvil JSON-RPC with `--auto-impersonate`.

```python
from core.replay import Replayer

replayer = Replayer(rpc_url="http://127.0.0.1:8545")
receipt = replayer.replay_transaction(tx_hash="0x...", warmup_txs=["0x...", "0x..."])
print(receipt.status, receipt.gas_used)
```

### `core.mutate.MutationPlan`
Defines counterfactual interventions applied to local fork state prior to replaying the target transaction.

- `FlashLoanSuppression(provider_address)`: Intercepts and zeroes flash-borrow returns.
- `OraclePinning(oracle_address, price_slot_value)`: Overwrites price feed storage slots.
- `SwapSlicing(ratio=0.75)`: Scales slippage parameters in top-level calldata.
- `ProxyAdminRevocation(proxy_address)`: Clears EIP-1967 admin storage slot.

### `core.outcome.OutcomeGuard`
Formal outcome classifier enforcing validity and harm reduction contracts.

```python
from core.outcome import classify_outcome, Verdict

verdict = classify_outcome(
    baseline_loss=1_500_000,
    mutated_loss=0,
    reverted=False,
    l_min=100_000
)
assert verdict == Verdict.CAUSE
```

---

## 2. Evaluation CLI Suite (`eval`)

### Multi-View Screener (`eval.e1_cli`)
```bash
python -m eval.e1_cli [--mode stratified | chronological | leave_one_family_out] [--include-near-negatives]
```

### State Fidelity Verification (`eval.fidelity_cli`)
```bash
python -m eval.fidelity_cli --dataset corpus/incidents.jsonl
```

### Causal Necessity Verification (`eval.necessity_cli`)
```bash
python -m eval.necessity_cli --case cream --lmin 100000
```

### Pilot Replay Harness (`pilot/run_case.py`)
```bash
python pilot/run_case.py --case <cream|euler|wazirx|bzx|radiant|arbitrage>
```

---

## 3. Go EVM Replay Engine (`tools/geth-replay`)

Direct bytecode replayer utilizing `go-ethereum` core EVM.

```bash
cd tools/geth-replay
./geth-replay -trace <path_to_prestate_trace.json> -verify-proofs

For a target transaction, `--emit-opcode-telemetry` additionally emits an
`opcode_telemetry` array.  Unlike the legacy `opcode_tail`, each event carries
the authenticated tracing context available from Geth's live hooks: stable
`frame_id`, caller/address, call input/value, full EVM stack, selected memory,
return data, and storage-context/slot operands.  This output is telemetry for
dependency analysis; it does not by itself authorize a causal intervention.
For large traces, add `--compact-opcode-telemetry` to retain the full stack and
frame/return/storage provenance while omitting repeated full-memory snapshots
and repeated frame calldata.
For very large traces, add `--opcode-telemetry-ndjson <path>` as well; this
writes one event per line and omits the telemetry array from the aggregate
replay JSON. `eval/e5/run_dynamic_provenance.py --input-ndjson <path>` consumes
that sidecar incrementally.
```
- **Inputs:** `prestateTracer` snapshot containing storage slots, balances, nonces, and bytecodes.
- **Outputs:** Gas consumed, execution receipt status, Merkle state trie proof verification.

### Authenticated provenance and harm-anchored slices

```bash
python -m eval.e5.run_dynamic_provenance \
  --input-ndjson <telemetry.ndjson.gz> \
  --allow-frame-bootstrap \
  --output <provenance.json>

python -m eval.e5.harm_sink_binding \
  --provenance <provenance.json> --spec <harm-spec.json> \
  --output <binding.json>

python -m eval.e5.provenance_harm_slice \
  --input <provenance.json> --sink-observation-id <observation> \
  --output <value-slice.json>

python -m eval.e5.control_candidate_slice \
  --input <provenance.json> --sink-observation-id <observation> \
  --output <control-candidates.json>
```

The binding layer is deterministic and fail-closed on zero or multiple
matches. Value/control slices are dependency diagnostics only; neither module
creates a causal verdict. `control_dependence_slice.py` provides the stricter
bounded CFG/post-dominator proof layer and marks oversized or non-convergent
frames unresolved.
