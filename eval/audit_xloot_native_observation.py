"""Audit XLoot native-ETH harm using materialized B2 observation."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from eval.m6_harm_adapters import assess_xloot_native_eth

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--observation", type=Path, default=ROOT / "eval/results/m6_xloot_native_observation.json")
    parser.add_argument("--out", type=Path, default=ROOT / "eval/results/m6_xloot_native_harm_audit.json")
    args = parser.parse_args()
    observation = json.loads(args.observation.read_text())
    if observation.get("observation_scope") != "transaction":
        raise SystemExit("observation_scope must be transaction")
    execution = observation.get("execution_observation")
    if not isinstance(execution, dict) or "harm_point_reached" not in execution:
        raise SystemExit("execution_observation.harm_point_reached missing")
    price = 2335.89367152
    owner = observation["protected_entity"]
    target = {"balance_changes": [{
        "address": owner,
        "previous": observation["pre_balance_wei"],
        "current": observation["post_balance_wei"],
    }]}
    spec = {
        "protected_entity": owner,
        "asset_kind": "native_eth",
        "usd_per_token": price,
        "lmin_usd": 20000,
        "price_reference_block": observation["state_block"],
        "target_block": observation["target_block"],
        "price_provenance": {"native_eth": {
            "reference_block": observation["state_block"],
            "source": "Chainlink ETH/USD feed 0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419 via eth_call latestRoundData",
        }},
    }
    result = assess_xloot_native_eth(target, spec)
    output = {
        "schema_version": 1,
        "status": result.status,
        "case_id": observation["case_id"],
        "baseline": {
            "harm_status": result.status,
            "harm_usd": result.loss_usd,
            "reason": result.reason,
            "protected_entity": owner,
            "debit_wei": observation["debit_wei"],
            "price_usd_per_eth": price,
            "lmin_usd": 20000,
        },
        "observation": observation,
        "scope": "baseline harm only; no causal mutation authorized by this artifact",
    }
    args.out.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    print(json.dumps(output, indent=2))
    return 0 if result.status == "HARM" else 2


if __name__ == "__main__":
    raise SystemExit(main())
