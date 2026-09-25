"""Inventory raw-trace candidate extraction across the fixed-20 and 80-case set.

This is an acquisition/coverage report, not a causal benchmark.  It refuses
to invent harm nodes or score candidates when authenticated trace evidence is
missing.
"""
from __future__ import annotations

import argparse, json
from pathlib import Path
from eval.e5.trace_candidate_extractor import extract_b2_call_nodes

ROOT = Path(__file__).resolve().parents[2]
M4 = ROOT / "eval/results/m4/b2-contexts-fresh"

def _b2(case_id):
    p = M4 / case_id / "b2-replay-m4.json"
    return p if p.exists() else None

def run(e4_path: Path, hard_path: Path):
    e4=[]
    for row in (json.loads(x) for x in e4_path.read_text().splitlines() if x.strip()):
        case_id=row["case_id"]; p=_b2(case_id)
        if not p:
            e4.append({"case_id":case_id,"status":"NOT_OBSERVABLE_NO_B2_TRACE"}); continue
        nodes=extract_b2_call_nodes(p)
        e4.append({"case_id":case_id,"status":"HARM_NODE_REQUIRED","b2_trace":str(p.relative_to(ROOT)),"raw_call_nodes":len(nodes),"harm_node_source":"not supplied by inventory"})
    hard_rows=[json.loads(x) for x in hard_path.read_text().splitlines() if x.strip()]
    groups={}
    for row in hard_rows:
        cid=row["incident_case_id"]; groups.setdefault(cid,[]).append(row)
    hard=[]
    for cid,rows in sorted(groups.items()):
        hard.append({"incident_case_id":cid,"candidate_transaction_count":len(rows),"status":"NOT_OBSERVABLE_NO_AUTHENTICATED_CANDIDATE_TRACE","available_b2_for_incident":_b2(cid) is not None})
    return {"schema_version":"e5-corpus-candidate-inventory-v1","status":"COVERAGE_ONLY","fixed20":{"case_count":len(e4),"cases":e4},"hard_negative_80":{"incident_case_count":len(hard),"candidate_transaction_count":len(hard_rows),"cases":hard},"limitations":["no harm node inference","hard-negative candidate transactions lack authenticated B2 traces","no Top-k or causal verdict"]}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--e4",type=Path,default=ROOT/"corpus/annotations/review_bundles/e4_reviewer_a.jsonl"); ap.add_argument("--hard",type=Path,default=ROOT/"corpus/annotations/review_bundles/hard_negatives_reviewer_a.jsonl"); ap.add_argument("-o","--output",type=Path,required=True); a=ap.parse_args(); a.output.write_text(json.dumps(run(a.e4,a.hard),indent=2)+"\n")

if __name__=="__main__": main()
