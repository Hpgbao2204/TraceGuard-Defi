"""Build a blind B3 pilot review queue from B2 candidates."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

def main():
    rows=[]; seen=set()
    for line in (ROOT / "corpus/vnext/hard_negative_candidates.jsonl").read_text().splitlines():
        x=json.loads(line); key=(x["chain"],x["tx_hash"])
        if key in seen: continue
        seen.add(key)
        rows.append({"tx_hash":x["tx_hash"],"anchor_id":x.get("anchor_address"),"incident_id":x["incident_id"],"chain":x["chain"],"tx_block":x["tx_block"],"review_label":None,"review_evidence":[],"reviewer_id":None,"reviewed_at":None,"source_shape_evidence":{"log_event_count":x.get("shape_features",{}).get("log_event_count")},"blindness_policy":"No model score/prediction included; historical traffic is not presumed benign."})
    rows.sort(key=lambda x:(x["chain"],x["tx_block"],x["tx_hash"]))
    d=ROOT / "corpus/vnext"; p=d / "hard_negative_pilot_review_queue.jsonl"; p.write_text("".join(json.dumps(x,sort_keys=True)+"\n" for x in rows))
    manifest={"schema_version":1,"stage":"B3","pilot_n":len(rows),"unique_transactions":len(rows),"labels_allowed":["VERIFIED_BENIGN","KNOWN_MALICIOUS","PROTOCOL_MISUSE","WHITEHAT_RESCUE","UNCERTAIN"],"model_predictions_included":False,"source_candidates_sha256":hashlib.sha256((d/"hard_negative_candidates.jsonl").read_bytes()).hexdigest(),"status":"PENDING_BLIND_REVIEW"}
    (d / "hard_negative_pilot_manifest.json").write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n"); print(json.dumps(manifest,indent=2))

if __name__ == "__main__":
    main()
