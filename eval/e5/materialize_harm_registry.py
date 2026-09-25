"""Materialize a conservative fixed-20 harm registry from existing artifacts."""
from __future__ import annotations
import argparse, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

def run(review_path: Path, source_manifest: Path) -> dict:
    review = [json.loads(x) for x in review_path.read_text().splitlines() if x.strip()]
    source = json.loads(source_manifest.read_text())
    known = {c["case_id"]: c.get("harm_node") for c in source["cases"] if c.get("harm_node")}
    cases=[]
    for row in review:
        cid=row["case_id"]
        if cid in known:
            cases.append({"case_id":cid,"status":"FROZEN_DIAGNOSTIC","harm_node":known[cid],"source_artifact":str(source_manifest.relative_to(ROOT))})
        else:
            cases.append({"case_id":cid,"status":"PENDING_HARM_BOUNDARY","harm_node":None,"reason":"no existing authenticated harm-node artifact"})
    return {"schema_version":"e5-harm-node-registry-v1","scope":"fixed-20 diagnostic registry","cases":cases,"summary":{"case_count":len(cases),"frozen_count":sum(c["status"]=="FROZEN_DIAGNOSTIC" for c in cases),"pending_count":sum(c["status"]!="FROZEN_DIAGNOSTIC" for c in cases)}}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("-o","--output",type=Path,required=True); ap.add_argument("--review",type=Path,default=ROOT/"corpus/annotations/review_bundles/e4_reviewer_a.jsonl"); ap.add_argument("--source",type=Path,default=ROOT/"eval/results/e5_rcfh/causal_candidate_v3_manifest.json"); a=ap.parse_args(); a.output.write_text(json.dumps(run(a.review,a.source),indent=2)+"\n")

if __name__=="__main__": main()
