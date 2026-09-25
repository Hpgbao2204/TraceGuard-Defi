"""Record conservative manual anchors from immutable source snapshots."""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ANCHORS = {
    "defihacklabs-aic-2026-08-03": ["0xc0DC449De632586A00409873521AFC251aC5cE74", "0x974C0078740480aE830D379fDB8d5f441C9dDC75"],
    "defihacklabs-moke-2026-08-02": ["0x684D722EbF8980f49492f631f56765DD4Fb302A7"],
    "defihacklabs-lula-2026-07-26": ["0xf0b36389a12a28be1280c0eC2a4bbc76889d6a96"],
    "defihacklabs-pro-token-2026-07-25": ["0x63844BD4BFad910B1643713302a1cC1ed20d50c3"],
    "defihacklabs-crowdringcircle-2026-07-16": ["0xd8799A644850c065388c22DF4eE0C28472922526"],
    "defihacklabs-unprotectedarbbot-2026-07-30": [],
    "defihacklabs-perpetual-protocol-2026-07-16": [],
}

def main():
    rows = []
    source = ROOT / "eval/vnext/recovery/source_provenance_git_history.jsonl"
    for line in source.read_text().splitlines():
        r = json.loads(line)
        if r["incident_id"] not in ANCHORS:
            continue
        addresses = ANCHORS[r["incident_id"]]
        valid = [a for a in addresses if len(a) == 42]
        rows.append({"incident_id": r["incident_id"], "attack_tx": r["tx_hash"], "chain": r["chain"], "exact_vulnerable_contracts": valid, "anchor_relation": "direct_victim", "relevant_function_selectors": [], "relevant_function_names": [], "evidence_source": "immutable Git-history source snapshot", "evidence_snapshot_sha256": r["snapshot_sha256"], "evidence_commit_or_archive_ref": r["commit_sha"], "deployment_block": None, "attack_block": None, "anchor_status": "VERIFIED_ANCHOR" if valid else "NO_EXACT_ANCHOR", "note": "Function/deployment fields remain blank unless explicitly bound by source or trace; abbreviated source addresses are not promoted."})
    dest = ROOT / "corpus/vnext"
    dest.mkdir(exist_ok=True)
    (dest / "contract_anchor_review_a4.jsonl").write_text("".join(json.dumps(x, sort_keys=True) + "\n" for x in rows))
    summary = {"schema_version": 1, "records": len(rows), "verified_anchor": sum(x["anchor_status"] == "VERIFIED_ANCHOR" for x in rows), "ambiguous": sum(x["anchor_status"] == "AMBIGUOUS" for x in rows), "no_exact_anchor": sum(x["anchor_status"] == "NO_EXACT_ANCHOR" for x in rows), "status": "MANUAL_REVIEW_RECORDED"}
    (dest / "contract_anchor_review_a4_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=2))

if __name__ == "__main__":
    main()
