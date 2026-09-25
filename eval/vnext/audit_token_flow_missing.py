"""Classify token-flow gaps without converting missing evidence to zero."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
TARGETS={'0x92be5e374e260192f8fdb5ffdc33504c768ecad091cc7dbc37282e5ca8ea94c6','0xa413fdf688398348ddf0246275c6fe3a98806670252e44bfe0acd50b4d50efa2'}
def main():
    cache={}
    paths=[ROOT/'eval/results/e1_trace_cache.jsonl',*Path(ROOT/'eval/vnext/acquisition').glob('*_positive_trace_cache.jsonl')]
    for p in paths:
        if p.exists():
            for line in p.read_text().splitlines():
                try:
                    x=json.loads(line)
                    if x.get('tx_hash') in TARGETS: cache[x['tx_hash']]=x
                except: pass
    rows=[]
    for h in sorted(TARGETS):
        x=cache.get(h,{}); logs=(x.get('trace') or {}).get('logs') or []
        rows.append({'tx_hash':h,'status':x.get('status'),'source':x.get('source'),'logs_present':bool(logs),'logs_count':len(logs),'erc20_transfer_events':sum(1 for z in logs if str((z.get('topics') or [''])[0]).lower().startswith('0xddf252ad')),'classification':'NO_TRANSFER_EVENTS_OBSERVED' if logs else 'LOGS_MISSING','coverage_decision':'PENDING_PREREGISTERED_NO_TRANSFER_POLICY'})
    out={'schema_version':1,'status':'AUDITED_PENDING_POLICY','policy':'Do not treat absent Transfer events as score 0 until no-transfer coverage semantics are frozen.','rows':rows}
    path=ROOT/'eval/vnext/gates/gate_v0_2b_token_flow_audit.json'; path.parent.mkdir(exist_ok=True,parents=True); path.write_text(json.dumps(out,indent=2,sort_keys=True)+'\n'); print(json.dumps(out,indent=2))
if __name__=='__main__': main()
