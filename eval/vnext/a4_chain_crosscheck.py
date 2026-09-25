"""Record A4 independent chain cross-checks for git-history snapshots."""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OBS = {
  "defihacklabs-aic-2026-08-03": ("0x6c82e78", "0x1"),
  "defihacklabs-moke-2026-08-02": ("0x6c63381", "0x1"),
  "defihacklabs-lula-2026-07-26": ("0x6b6fc1e", "0x1"),
  "defihacklabs-pro-token-2026-07-25": ("0x6b6f6be", "0x1"),
  "defihacklabs-crowdringcircle-2026-07-16": ("0x6931154", "0x1"),
  "defihacklabs-unprotectedarbbot-2026-07-30": ("0x2f051d0", "0x1"),
  "defihacklabs-perpetual-protocol-2026-07-16": ("0x9329b08", "0x1"),
}
def main() -> None:
    src = ROOT / "eval/vnext/recovery/source_provenance_git_history.jsonl"
    out = ROOT / "eval/vnext/recovery"
    rows=[]
    for line in src.read_text().splitlines():
        r=json.loads(line)
        if r["incident_id"] not in OBS: continue
        block,status=OBS[r["incident_id"]]
        r.update({"a4_provider_crosscheck":"external-network-json-rpc",
                  "a4_tx_inclusion":True,"a4_receipt":True,
                  "a4_block":block,"a4_receipt_status":status,
                  "p2_pass":True,"p3_pass":True,
                  "promotion_ready":r["status"]=="SOURCE_SNAPSHOT_READY" and r["hash_explicit_in_snapshot"]})
        rows.append(r)
    p=out/"positive_a4_chain_crosscheck.jsonl"
    p.write_text("".join(json.dumps(r,sort_keys=True)+"\n" for r in rows))
    s={"schema_version":1,"stage":"A4.1","records":len(rows),"p2_pass":sum(r["p2_pass"] for r in rows),"p3_pass":sum(r["p3_pass"] for r in rows),"promotion_ready":sum(r["promotion_ready"] for r in rows),"source":"external RPC fallback; raw credentials not recorded","status":"P2_P3_READY_PENDING_P1_MANUAL_CONFIRMATION"}
    (out/"positive_a4_chain_crosscheck_summary.json").write_text(json.dumps(s,indent=2,sort_keys=True)+"\n")
    print(json.dumps(s,indent=2))
if __name__ == "__main__": main()
