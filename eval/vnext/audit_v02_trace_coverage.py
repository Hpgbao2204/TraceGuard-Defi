"""Audit vNext positive trace and view coverage without acquiring network data."""
from __future__ import annotations
import json, hashlib
from collections import Counter
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
RECOVERED = ROOT/'eval/vnext/acquisition/bsc_positive_trace_cache.jsonl'
RECOVERED_OTHER = [ROOT/f'eval/vnext/acquisition/{c}_positive_trace_cache.jsonl' for c in ('ethereum','arbitrum','optimism')]
sys.path.insert(0,str(ROOT))
from eval.vnext.vnext_contract import VNEXT_B0_VIEWS
from core.views import evaluate_all
from eval.e1_common import load_cache_rows, trace_from_cache

def main():
    pos=[json.loads(x) for x in (ROOT/'corpus/vnext/positive_transactions.jsonl').read_text().splitlines() if x.strip()]
    cache=load_cache_rows(ROOT/'eval/results/e1_trace_cache.jsonl')
    if RECOVERED.exists(): cache.update(load_cache_rows(RECOVERED))
    for recovered in RECOVERED_OTHER:
        if recovered.exists(): cache.update(load_cache_rows(recovered))
    missing=[x for x in pos if x['tx_hash'] not in cache]
    transaction_available=[x for x in pos if x['tx_hash'] in cache and not cache[x['tx_hash']].get('error')]
    available=[x for x in pos if x['tx_hash'] in cache and cache[x['tx_hash']].get('source') == 'callTracer' and (cache[x['tx_hash']].get('trace') or {}).get('tree')]
    by_chain=Counter(x.get('chain') for x in missing)
    total=Counter(); covered=Counter(); missing_views=Counter()
    for p in available:
        res=evaluate_all(trace_from_cache(cache[p['tx_hash']].get('trace') or {}), {})
        for v in VNEXT_B0_VIEWS:
            total[v]+=1
            logs=(cache[p['tx_hash']].get('trace') or {}).get('logs') or []
            no_transfer = not any(str((z.get('topics') or [''])[0]).lower().startswith('0xddf252ad') for z in logs)
            observed_zero_token = v == 'token_flow' and not res.get(v,{}).get('coverage') and cache[p['tx_hash']].get('status') is True and bool(logs) and no_transfer
            if res.get(v,{}).get('coverage') or observed_zero_token: covered[v]+=1
            else: missing_views[v]+=1
    calltrace_missing=[x for x in pos if x not in available]
    out={'schema_version':1,'status':'FAIL','feature_contract':'vnext-b0-3view-v1','views':list(VNEXT_B0_VIEWS),'source_positive_sha256':hashlib.sha256((ROOT/'corpus/vnext/positive_transactions.jsonl').read_bytes()).hexdigest(),'source_cache_sha256':hashlib.sha256((ROOT/'eval/results/e1_trace_cache.jsonl').read_bytes()).hexdigest(),'recovered_cache_sha256s':{p.stem:hashlib.sha256(p.read_bytes()).hexdigest() for p in [RECOVERED,*RECOVERED_OTHER] if p.exists()},'requested_positive_rows':len(pos),'transaction_available_rows':len(transaction_available),'calltrace_available_rows':len(available),'calltrace_missing_rows':len(calltrace_missing),'missing_trace_by_chain':dict(sorted(by_chain.items(),key=lambda x:str(x[0]))),'view_rows':dict(total),'view_covered':dict(covered),'view_missing':dict(missing_views),'policy':'tx+receipt is not callTracer; no missing view is converted to 0.0.','next_action':'Acquire callTracer traces and audit provider/parser shape.'}
    path=ROOT/'eval/vnext/gates/gate_v0_2a_trace_coverage.json'; path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(out,indent=2,sort_keys=True)+'\n'); print(json.dumps(out,indent=2,sort_keys=True))
if __name__=='__main__': main()
