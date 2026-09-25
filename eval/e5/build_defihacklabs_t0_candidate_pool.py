"""Build a rule-selected DeFiHackLabs expansion pool for T0 validation.

This is candidate acquisition only.  It never promotes incident loss to
transaction-level HARM_GOLD and never selects on T0 output.
"""
from __future__ import annotations
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "corpus/incidents.jsonl"
OUT = ROOT / "eval/results/e5_rcfh/defihacklabs_t0_candidate_pool.json"

SUPPORTED = {"ethereum", "arbitrum", "polygon", "avalanche", "optimism", "fantom", "bsc"}
FAMILY = {
    "governance/access": "access_control",
    "accounting": "accounting_share",
    "oracle": "oracle_valuation",
    "flash-loan": "asset_drain",
    "reentrancy": "asset_drain",
    "token": "asset_drain",
    "precision": "accounting_share",
    "bridge": "bridge_state",
    "rug-pull": "asset_drain",
}


def main():
    rows = [json.loads(line) for line in SRC.read_text().splitlines() if line.strip()]
    candidates, rejected = [], Counter()
    for r in rows:
        reasons = []
        txs = [x for x in r.get("tx_hashes", []) if isinstance(x, str) and x.startswith("0x") and len(x) == 66]
        if r.get("class") != "attack": reasons.append("not_attack")
        if r.get("chain") not in SUPPORTED: reasons.append("unsupported_or_unknown_chain")
        if not txs: reasons.append("missing_exact_tx")
        if r.get("verified") != "onchain": reasons.append("tx_not_verified_onchain")
        if not r.get("source_url"): reasons.append("missing_source")
        if reasons:
            rejected.update(reasons)
            continue
        attack_type = r.get("attack_type") or "other"
        candidates.append({
            "candidate_id": r["id"], "source": "DeFiHackLabs",
            "incident": {"protocol": r.get("protocol"), "date": r.get("date"), "loss_usd": r.get("loss_usd")},
            "transaction": {"chain": r.get("chain"), "tx_hashes": txs, "block": r.get("block"), "verified": r.get("verified")},
            "reported_root_cause": {"attack_type": attack_type, "family": FAMILY.get(attack_type, "other"), "gt_factors": r.get("gt_factors", [])},
            "provenance": {"source_url": r.get("source_url"), "notes": r.get("notes", "")},
            "harm_gold_status": "PENDING_ADJUDICATION",
            "t0_status": "NOT_RUN",
        })
    by_family = Counter(x["reported_root_cause"]["family"] for x in candidates)
    by_chain = Counter(x["transaction"]["chain"] for x in candidates)
    out = {
        "schema_version": 1, "artifact": "defihacklabs-t0-candidate-pool-v1",
        "source": "corpus/incidents.jsonl", "source_record_count": len(rows),
        "selection_policy": {
            "include": ["class=attack", "supported EVM chain", "exact 32-byte tx hash", "verified=onchain", "source URL"],
            "exclude": ["private-key/phishing only where no replayable contract harm target", "unsupported chain", "missing/unverified tx"],
            "selection_independent_of_t0": True,
        },
        "candidate_count": len(candidates), "candidates": candidates,
        "counts": {"by_family": dict(by_family), "by_chain": dict(by_chain), "rejected_reasons": dict(rejected)},
        "status": "CANDIDATE_POOL_ONLY",
        "next_gates": ["canonical replay/B2", "protected-entity adjudication", "harm-family assignment review", "transaction_harm_gold materialization", "frozen train-validation-test split"],
    }
    OUT.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"candidate_count": len(candidates), "by_family": dict(by_family), "by_chain": dict(by_chain)}, indent=2))


if __name__ == "__main__": main()
