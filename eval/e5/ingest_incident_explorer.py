"""Ingest the public Incident Explorer RCA source into a hash-bound excerpt.

The full upstream dataset is not copied into the repository. This artifact
records only matched fixed-20 entries plus upstream URL/hash and match mode.
"""
from __future__ import annotations
import hashlib, json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE_URL = "https://raw.githubusercontent.com/SunWeb3Sec/DeFiHackLabs-Incident-Explorer/main/rootcause_data.json"
OUT = ROOT / "eval/results/e5_rcfh/incident_explorer_matches.json"


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def main(path: str = "/tmp/e5_rootcause_data.json") -> None:
    raw = Path(path).read_bytes()
    source = json.loads(raw)
    manifest = json.loads((ROOT / "docs/m4_frozen_case_manifest.json").read_text())["cases"]
    matches = []
    for c in manifest:
        tx = c["tx_hash"].lower()
        base = c["case_id"].removeprefix("defihacklabs-").rsplit("-", 3)[0]
        exact = []
        fuzzy = []
        for name, record in source.items():
            text = json.dumps(record).lower()
            if tx in text:
                exact.append((name, record))
            elif norm(name) == norm(base):
                fuzzy.append((name, record))
        chosen = exact or fuzzy
        if len(chosen) == 1:
            name, record = chosen[0]
            matches.append({
                "case_id": c["case_id"], "tx_hash": c["tx_hash"],
                "source_name": name,
                "match_confidence": "EXACT_TX_HASH" if exact else "FUZZY_PROTOCOL_NAME",
                "claim_type": record.get("type"),
                "root_cause": record.get("rootCause"),
                "attack_transaction_excerpt": record.get("rootCause", "").split("Analysis:")[0][-1000:],
                "source_record_sha256": hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest(),
            })
    result = {
        "schema_version": 1, "artifact": "e5-incident-explorer-independent-source",
        "corpus_id": "m4-frozen-20", "source_url": SOURCE_URL,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "source_record_count": len(source), "matched_count": len(matches),
        "matches": matches,
        "limitation": "This is an independent RCA claim source, not ground truth; fuzzy protocol-name matches are separate from exact tx-hash matches.",
    }
    OUT.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"matched": len(matches), "exact": sum(x["match_confidence"] == "EXACT_TX_HASH" for x in matches), "fuzzy": sum(x["match_confidence"] != "EXACT_TX_HASH" for x in matches)}, indent=2))


if __name__ == "__main__": main()
