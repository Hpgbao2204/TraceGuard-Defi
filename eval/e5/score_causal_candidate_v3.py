"""Score v3 raw-trace candidates against separate hidden references."""
from __future__ import annotations
import argparse, json
from pathlib import Path

def score(run_result, refs):
    out=[]
    for c in run_result.get("cases", []):
        rs=refs.get("references",{}).get(c["case_id"],[])
        if c.get("status") != "REVIEW_REQUIRED": out.append({"case_id":c["case_id"],"status":"NOT_OBSERVABLE"}); continue
        keys={(r.get("selector"),r.get("trace_index")) for r in rs}
        pos=[i+1 for i,n in enumerate(c["ranked_candidates"]) if (n.get("selector"),n.get("trace_index")) in keys]
        out.append({"case_id":c["case_id"],"status":"SCORED","reference_positions":pos,
                    "top1_hit":any(x<=1 for x in pos),"top3_hit":any(x<=3 for x in pos),"top5_hit":any(x<=5 for x in pos),
                    "candidate_count":c["candidate_count"],"initial_node_count":c["initial_node_count"],"reduction_ratio":c["reduction_ratio"]})
    obs=[x for x in out if x["status"]=="SCORED"]
    return {"schema_version":"e5-causal-candidate-score-v3","scope":"hidden scoring only","case_scores":out,
            "summary":{"observable_scored":len(obs),"top1":f"{sum(x['top1_hit'] for x in obs)}/{len(obs)}","top3":f"{sum(x['top3_hit'] for x in obs)}/{len(obs)}","top5":f"{sum(x['top5_hit'] for x in obs)}/{len(obs)}"},"causal_verdict_count":0}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("runner_output",type=Path); ap.add_argument("hidden_refs",type=Path); ap.add_argument("-o", "--output",type=Path,required=True); a=ap.parse_args()
    a.output.write_text(json.dumps(score(json.loads(a.runner_output.read_text()),json.loads(a.hidden_refs.read_text())),indent=2)+"\n")

if __name__ == "__main__": main()
