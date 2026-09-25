"""Build a fail-closed review queue for multi-transaction incidents."""
from __future__ import annotations
import hashlib, json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REG = ROOT / "corpus/vnext/positive_registry.jsonl"
OUT = ROOT / "corpus/vnext/positive_multitx_canonical_review_queue.jsonl"
MANIFEST = ROOT / "corpus/vnext/positive_multitx_canonical_review_manifest.json"

def main() -> None:
    rows = []
    for line in REG.read_text().splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        hashes = [h for h in item.get("tx_hashes", []) if h]
        if len(hashes) <= 1:
            continue
        rows.append({
            "incident_id": item["incident_id"],
            "chain": item.get("chain"),
            "tx_hashes": hashes,
            "canonical_attack_tx": None,
            "tx_roles": {h: None for h in hashes},
            "review_status": "PENDING_INDEPENDENT_REVIEW",
            "reviewer_id": None,
            "reviewer_note": None,
        })
    OUT.write_text("".join(json.dumps(x, sort_keys=True) + "\n" for x in rows))
    manifest = {
        "schema_version": 1,
        "purpose": "V0.1 canonical transaction review; no automatic selection",
        "source_path": str(REG.relative_to(ROOT)),
        "source_sha256": hashlib.sha256(REG.read_bytes()).hexdigest(),
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "incident_count": len(rows),
        "status": "PENDING_INDEPENDENT_REVIEW",
        "allowed_tx_roles": ["exploit", "setup", "approval", "drain", "sweep", "auxiliary"],
        "output_sha256": hashlib.sha256(OUT.read_bytes()).hexdigest(),
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps(manifest, indent=2, sort_keys=True))

if __name__ == "__main__":
    main()
