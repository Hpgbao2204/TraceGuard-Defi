"""Materialize an exploratory, transaction-scoped native balance observation."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTEXT = ROOT / "eval/results/m6/dependency-contexts/xtoken-xsnxa"
OUT = ROOT / "eval/exploratory/xtoken_xsnxa_b2_observation.json"
POOL = "0x7cd5e2d0056a7a7f09cbb86e540ef4f6dccc97dd"


def main() -> int:
    payload = json.loads((CONTEXT / "poststates.json").read_text())
    item = payload[0]
    before = int(item["prestate"][POOL]["balance"], 16)
    after = int(item["poststate"][POOL]["balance"], 16)
    observation = {
        "status": "OBSERVED_CANDIDATE",
        "classification": "NOT_PREREGISTERED — exploratory baseline only",
        "counted_in_fixed_20": False,
        "observation_scope": "transaction",
        "scope_definition": "state immediately before and immediately after target transaction",
        "target": {"tx_hash": item["tx_hash"], "block": 12419918, "tx_index": 0},
        "identity_screen": {
            "pool_candidate": POOL,
            "explorer_label": "xSNX: xSNXa Token",
            "creator_label": "xToken: Deployer",
            "target_trace_role": "pool candidate sends native ETH to xSNXa token contract",
            "status": "PLAUSIBLE_NOT_PROOF_OF_PROTECTED_HARM",
            "source": "Etherscan address/transaction pages; labels are report-level corroboration",
        },
        "protected_entities": [{"address": POOL, "assets": [{
            "asset_type": "native", "asset_id": "ETH",
            "before_raw": str(before), "after_raw": str(after),
            "delta_raw": str(after - before),
        }]}],
        "execution_observation": {
            "harm_point_reached": True,
            "baseline_b2_acceptance": True,
            "revert_location": None,
        },
        "b2_contract": {
            "proof_bound": True,
            "prestate_proof_complete": True,
            "accounts_verified": 125,
            "storage_cells_verified": 583,
            "state_root_scope": "transaction-relevant authenticated substate; not full world state",
        },
        "harm_spec": {
            "status": "UNFROZEN_FOR_XSNXA",
            "note": "Do not apply XLoot's 0.5 ETH rule or issue a causal verdict before protected-entity adjudication and frozen policy."
        },
    }
    OUT.write_text(json.dumps(observation, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(OUT), "sha256": hashlib.sha256(OUT.read_bytes()).hexdigest(),
                      "before_raw": str(before), "after_raw": str(after),
                      "delta_raw": str(after - before)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
