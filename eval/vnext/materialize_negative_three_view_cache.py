"""Materialize frozen negative traces into the vNext three-view contract."""
import hashlib,json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from core.views import evaluate_all
from eval.e1_common import trace_from_cache
from eval.vnext.vnext_contract import VNEXT_B0_FEATURE_CONTRACT_VERSION,VNEXT_B0_VIEWS
REG=ROOT/'eval/vnext/negatives/negative_registry_v1.jsonl'
CACHE=ROOT/'eval/vnext/acquisition/negative_trace_cache.jsonl'
OUT=ROOT/'eval/vnext/features/negative_three_view_feature_cache.jsonl'
def main():
    reg={x['tx_hash']:x for x in (json.loads(l) for l in REG.read_text().splitlines() if l.strip())}
    traces={x['tx_hash']:x for x in (json.loads(l) for l in CACHE.read_text().splitlines() if l.strip())}
    rows=[]
    for h,meta in sorted(reg.items()):
        src=traces.get(h)
        if not src or not src.get('trace'): continue
        result=evaluate_all(trace_from_cache(src['trace']),{})
        scores={v:(result.get(v,{}).get('score') if result.get(v,{}).get('coverage') else None) for v in VNEXT_B0_VIEWS}
        logs=src.get('receipt_logs',[]); token=result.get('token_flow',{})
        # Trace + successful receipt with an observed (possibly empty) logs
        # array is complete evidence: no child calls/recognized flow is zero,
        # not missing. Missing is reserved for absent trace/receipt evidence.
        if result.get('call_structure',{}).get('coverage') == 0: scores['call_structure']=0.0
        if not token.get('coverage') and src.get('receipt_status') in ('0x1',1) and 'receipt_logs' in src: scores['token_flow']=0.0
        missing=[v for v in VNEXT_B0_VIEWS if scores[v] is None]
        rows.append({**meta,'feature_schema_version':VNEXT_B0_FEATURE_CONTRACT_VERSION,'scores':scores,'missing_views':missing,'coverage_complete':not missing,'trace_cache_source':str(CACHE.relative_to(ROOT))})
    OUT.parent.mkdir(parents=True,exist_ok=True); OUT.write_text(''.join(json.dumps(x,sort_keys=True)+'\n' for x in rows))
    print(json.dumps({'requested':len(reg),'rows':len(rows),'complete':sum(x['coverage_complete'] for x in rows),'missing':sum(not x['coverage_complete'] for x in rows),'cache_sha256':hashlib.sha256(OUT.read_bytes()).hexdigest()},indent=2))
if __name__=='__main__': main()
