"""Derive objective protected-entity candidates from frozen B2 traces."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CASES = {
    "defihacklabs-onyxdao-2024-09-26": "eval/results/m4/b2-contexts-fresh/defihacklabs-onyxdao-2024-09-26",
    "defihacklabs-alkemiearn-2026-03-10": "eval/results/m4/b2-contexts-fresh/defihacklabs-alkemiearn-2026-03-10",
    "defihacklabs-usm-2026-08-09": "eval/results/m4/b2-contexts-fresh/defihacklabs-usm-2026-08-09",
}


def derive(cid: str, rel: str) -> dict:
    root = ROOT / rel
    case = json.loads((root / "case.json").read_text())
    target = json.loads((root / "poststates.json").read_text())[-1]
    trace = target.get("calltrace") or {}
    accounts = []
    for address in sorted(set(target.get("prestate", {})) | set(target.get("poststate", {}))):
        pre = target.get("prestate", {}).get(address, {}).get("balance")
        post = target.get("poststate", {}).get(address, {}).get("balance")
        if pre is None and post is None:
            continue
        before = int(pre, 16) if isinstance(pre, str) else int(pre or 0)
        after = int(post, 16) if isinstance(post, str) else int(post or 0)
        if before != after:
            accounts.append({"address": address.lower(), "native_delta_wei": str(after - before)})
    return {
        "case_id": cid,
        "tx_hash": case["tx_hash"],
        "block": int(case["block"]),
        "tx_index": int(case["tx_index"]),
        "trace_root_target": str(trace.get("to", "")).lower(),
        "trace_root_sender": str(trace.get("from", "")).lower(),
        "native_balance_changes": accounts,
        "candidate_entity_rule": "trace root target is an objective call target; protected status requires independent protocol/evidence confirmation",
        "status": "CANDIDATES_REQUIRE_ADJUDICATOR_CONFIRMATION",
        "source": {
            "context_case": str(root / "case.json"),
            "poststates": str(root / "poststates.json"),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "eval/results/m6_protected_entity_candidates.json")
    args = parser.parse_args()
    result = {"schema_version": 1, "status": "CANDIDATE_MAP_ONLY", "cases": {
        cid: derive(cid, rel) for cid, rel in CASES.items()
    }}
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
