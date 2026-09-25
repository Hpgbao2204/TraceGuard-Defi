"""Audit existing incident rows for Gate A recovery; never promote labels."""
from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INPUT = ROOT / "corpus/incidents.jsonl"
OUT = ROOT / "eval/vnext/recovery"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    rows = [json.loads(x) for x in INPUT.read_text().splitlines() if x.strip()]
    tx_owner = defaultdict(list)
    for row in rows:
        for tx in row.get("tx_hashes", []):
            tx_owner[tx.lower()].append(row["id"])

    registry, rejected = [], []
    reasons = Counter()
    for row in rows:
        base = {"incident_id": row.get("id"), "source": row.get("source"), "chain": row.get("chain"),
                "protocol": row.get("protocol"), "tx_hashes": row.get("tx_hashes", []),
                "source_url": row.get("source_url"), "verified": row.get("verified")}
        txs = row.get("tx_hashes") or []
        if row.get("class") != "attack":
            reason = "NOT_ATTACK_CLASS"
        elif not txs:
            reason = "NO_TX_HASH"
        elif row.get("verified") != "onchain":
            reason = "NOT_CURRENTLY_ONCHAIN_VERIFIED"
        elif any(len(tx) != 66 or not tx.lower().startswith("0x") for tx in txs):
            reason = "MALFORMED_TX_HASH"
        elif any(len(tx_owner[tx.lower()]) > 1 for tx in txs):
            reason = "DUPLICATE_TRANSACTION_MAPPING"
        else:
            registry.append({**base, "usable_verified_attack": True})
            continue
        reasons[reason] += 1
        rejected.append({**base, "usable_verified_attack": False, "rejection_reason": reason})

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "positive_recovery_registry.jsonl").write_text("".join(json.dumps(x, sort_keys=True) + "\n" for x in registry))
    (OUT / "positive_recovery_rejections.jsonl").write_text("".join(json.dumps(x, sort_keys=True) + "\n" for x in rejected))
    summary = {
        "schema_version": 1, "status": "AUDIT_ONLY_NO_PROMOTION", "input": str(INPUT.relative_to(ROOT)),
        "input_sha256": sha(INPUT), "raw_rows": len(rows), "current_verified_registry_rows": len(registry),
        "rejected_rows": len(rejected), "rejection_counts": dict(reasons),
        "duplicate_transaction_keys": sum(1 for tx, ids in tx_owner.items() if len(ids) > 1),
        "policy": "Only existing verified=onchain rows count; blocked/ambiguous rows remain rejected.",
    }
    (OUT / "positive_recovery_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
