"""Freeze incident-level positive registry from verified base plus promotions."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

def main():
    base=[]
    for line in (ROOT / "corpus/incidents.jsonl").read_text().splitlines():
        x=json.loads(line)
        if x.get("verified") == "onchain" and x.get("id"):
            x["incident_id"] = x["id"]
            base.append(x)
    promos=[]
    for p in sorted((ROOT / "eval/vnext/recovery").glob("positive_provenance_promotions_v*.jsonl")):
        promos += [json.loads(x) for x in p.read_text().splitlines() if x.strip()]
    merged={x["incident_id"]:{"incident_id":x["incident_id"],"tx_hashes":x.get("tx_hashes",[]),"chain":x.get("chain"),"verification":"base_registry"} for x in base}
    for x in promos:
        if x.get("status") == "VERIFIED_ATTACK" and x.get("incident_id"):
            merged[x["incident_id"]]={"incident_id":x["incident_id"],"tx_hashes":[x.get("tx_hash")],"chain":x.get("chain"),"verification":"p1_p2_p3_recovery","evidence_refs":x.get("evidence_refs",[]),"source_snapshot_sha256":x.get("source_snapshot_sha256")}
    rows=sorted(merged.values(),key=lambda x:x["incident_id"]); d=ROOT / "corpus/vnext"; p=d / "positive_registry.jsonl"; p.write_text("".join(json.dumps(x,sort_keys=True)+"\n" for x in rows))
    m={"schema_version":1,"status":"FROZEN","record_unit":"unique_incident","verified_attack_incidents":len(rows),"source_registry_sha256":hashlib.sha256(p.read_bytes()).hexdigest(),"p7_mutated":False,"raw_corpus_mutated":False}; (d / "positive_registry_manifest.json").write_text(json.dumps(m,indent=2,sort_keys=True)+"\n"); print(json.dumps(m,indent=2))

if __name__ == "__main__":
    main()
