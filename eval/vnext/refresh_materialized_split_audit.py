"""Refresh V0 audit from current materialized artifacts; never rewrites inputs."""
import hashlib, json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def main():
    pos=[json.loads(x) for x in (ROOT/'corpus/vnext/positive_transactions.jsonl').read_text().splitlines() if x.strip()]
    feat=ROOT/'eval/vnext/features/three_view_feature_cache.jsonl'
    rows=[json.loads(x) for x in feat.read_text().splitlines() if x.strip()]
    audit=json.loads((ROOT/'eval/vnext/splits/materialized_split_audit.json').read_text())
    reasons=[]
    if len(rows)!=len(pos) or any(x.get('missing_views') for x in rows): reasons.append('TRACE_OR_VIEW_COVERAGE_INCOMPLETE')
    if len(rows)==len(pos) and all(not x.get('missing_views') for x in rows): reasons=[]
    reasons.append('NEGATIVE_REGISTRY_NOT_MATERIALIZED')
    audit.update({'required_views':['call_structure','token_flow','economic'],'feature_cache_rows':len(rows),'feature_schema_valid':bool(rows) and all(x.get('feature_schema_version')=='vnext-b0-3view-v1' for x in rows),'feature_cache_sha256':hashlib.sha256(feat.read_bytes()).hexdigest(),'negative_rows_materialized':0,'status':'FAIL','reason_codes':reasons})
    (ROOT/'eval/vnext/splits/materialized_split_audit.json').write_text(json.dumps(audit,indent=2,sort_keys=True)+'\n')
    print(json.dumps(audit,indent=2,sort_keys=True))
if __name__=='__main__': main()
