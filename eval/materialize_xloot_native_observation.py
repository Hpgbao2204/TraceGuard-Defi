"""Materialize XLoot protected native-ETH observation from frozen B2 context."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


OWNER = "0x9d87ff196646a99bddb16876066aa863900118b4"
ROOT = Path(__file__).resolve().parent.parent
CONTEXT = ROOT / "eval/results/m6/dependency-contexts/xlootstaking"
DEFAULT_OUT = ROOT / "eval/results/m6_xloot_native_observation.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def balance(entry: dict) -> int | None:
    value = entry.get("balance")
    if value is None:
        return None
    return int(value, 16) if isinstance(value, str) else int(value)


def materialize(context: Path, out: Path) -> dict:
    case = json.loads((context / "case.json").read_text())
    states = json.loads((context / "poststates.json").read_text())
    target = next((row for row in states if row.get("index") == case["tx_index"]), None)
    if target is None:
        raise ValueError("target poststate missing")
    owner = OWNER.lower()
    before = target.get("prestate", {}).get(owner)
    after = target.get("poststate", {}).get(owner)
    pre = balance(before or {})
    post = balance(after or {})
    if pre is None or post is None:
        raise ValueError("protected entity native balance missing")
    result = {
        "schema_version": 1,
        "status": "OBSERVED",
        "case_id": "defihacklabs-xlootstaking-2026-04-15",
        "tx_hash": case["tx_hash"],
        "target_block": int(case["block"]),
        "state_block": int(case["state_block"]),
        "tx_index": int(case["tx_index"]),
        "observation_scope": "transaction",
        "protected_entities": [{
            "address": owner,
            "assets": [{
                "asset_type": "native",
                "asset_id": "ETH",
                "before_raw": str(pre),
                "after_raw": str(post),
                "delta_raw": str(post - pre),
            }],
        }],
        "execution_observation": {
            "harm_point_reached": True,
            "revert_location": None,
        },
        # Compatibility fields retained for existing audit consumers.
        "protected_entity": owner,
        "asset_kind": "native_eth",
        "pre_balance_wei": str(pre),
        "post_balance_wei": str(post),
        "delta_wei": str(post - pre),
        "debit_wei": str(max(0, pre - post)),
        "source": {
            "context_manifest": str(context / "manifest.json"),
            "context_manifest_sha256": sha(context / "manifest.json"),
            "poststates": str(context / "poststates.json"),
            "poststates_sha256": sha(context / "poststates.json"),
            "observation_rule": "target poststate balance minus target prestate balance",
        },
    }
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", type=Path, default=CONTEXT)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    print(json.dumps(materialize(args.context, args.out), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
