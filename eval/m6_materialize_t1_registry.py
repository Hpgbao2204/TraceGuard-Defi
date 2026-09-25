"""Materialize only adjudicated T1 boundaries from frozen reviewer evidence.

This deliberately excludes Giddy: its frozen policy is receipt-token
redeemability/NAV, which is T2-style semantic harm rather than a hard-asset
boundary under hard-assets-v1.
"""
from __future__ import annotations
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "eval/results/m6_supplementary_reviewer_c_audit.json"
OUT = ROOT / "eval/results/m6_harm_t1_registry_v1.json"
ZERO = "0x" + "0" * 40

TARGETS = {
    "defihacklabs-alkimiya-io-2025-03-28": {"protocol_id": "alkimiya", "asset": "wbtc"},
    "defihacklabs-xlootstaking-2026-04-15": {"protocol_id": "xlootstaking", "asset": "eth"},
}

def main():
    raw = SOURCE.read_bytes()
    source = json.loads(raw)
    rows = []
    for row in source["cases"]:
        spec = TARGETS.get(row["case_id"])
        if not spec:
            continue
        if row.get("errors") or row.get("harm_status") != "MEASURABLE":
            continue
        entities = sorted({x.lower() for x in row.get("normalized_protected_entities", [])})
        assets = []
        for a in row.get("normalized_harm_assets", []):
            symbol = str(a.get("symbol", "")).lower()
            if symbol == spec["asset"]:
                assets.append({"symbol": symbol, "address": str(a.get("asset", "")).lower()})
        if spec["asset"] == "eth":
            assets = [{"symbol": "eth", "address": None}]
        if not entities or not assets:
            continue
        rows.append({
            "case_id": row["case_id"],
            "tier": "T1",
            "boundary_id": f"protocol-explicit-v1:{spec['protocol_id']}",
            "protocol_id": spec["protocol_id"],
            "protected_entities": entities,
            "hard_assets": assets,
            "attacker_addresses": [],
            "status": "FROZEN_ADJUDICATED",
            "tx_hash": row.get("tx_hash"),
            "source_artifact": str(SOURCE.relative_to(ROOT)),
            "source_sha256": hashlib.sha256(raw).hexdigest(),
            "valuation_required_for_detection": False,
            "scope_note": "T1 raw hard-asset boundary; USD and exotic/liability semantics excluded",
        })
    artifact = {
        "schema_version": 1,
        "registry_id": "m6-harm-t1-boundaries-v1",
        "hard_asset_registry": "hard-assets-v1",
        "status": "FROZEN_PARTIAL",
        "cases": rows,
        "excluded": {
            "GiddyVaultV3": "receipt-token redeemability/NAV is T2 semantic harm, not hard-assets-v1",
            "frozen-20": "no adjudicated protocol boundary in current input",
        },
    }
    OUT.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"rows": len(rows), "sha256": hashlib.sha256(OUT.read_bytes()).hexdigest()}, indent=2))

if __name__ == "__main__":
    main()
