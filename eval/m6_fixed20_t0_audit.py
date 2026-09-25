"""Read-only fixed-20 T0 audit from frozen B2 target traces."""
import json, glob
from pathlib import Path
from eval.m6_harm_v2 import t0
from eval.b2_run_select import select_canonical_run
from eval.attacker_set_v2 import derive
from eval.native_ledger_v1 import committed_native_delta
from eval.corpus_authority import assert_frozen20
from eval.e4.harm_vector import from_flows

ROOT=Path(__file__).resolve().parents[1]
MAN=ROOT/'docs/m4_frozen_case_manifest.json'
B2=ROOT/'eval/results/m6_b2_preflight.json'
OUT=ROOT/'eval/results/m6_harm_detection_v2_fixed20_t0.json'
INF=ROOT/'eval/e4/infra_v1.json'
TOPIC='0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef'

def load(p): return json.loads(Path(p).read_text())
def target_row(context, tx):
    try: return select_canonical_run(context, tx)
    except Exception: return None
def extract(row):
    trace=row.get('call_trace') or []
    root=next((x for x in trace if x.get('event')=='enter' and x.get('depth')==0),None)
    sender=(root or {}).get('from')
    attacker_set,created=derive(trace,sender)
    flows=[]; native=[]
    for i,x in enumerate(trace):
        if x.get('event')=='enter' and x.get('type')=='CALL':
            v=x.get('value')
            try:
                amount=int(str(v),0)
                if amount: native.append({'token':'eth','from':x.get('from',''),'to':x.get('to',''),'amount_raw':amount,'trace_index':i})
            except (TypeError,ValueError): pass
    for log in row.get('logs') or []:
        topics=log.get('topics') or []
        if topics and topics[0].lower()==TOPIC and len(topics)>=3:
            try: amount=int(log.get('data','0x0'),16)
            except (TypeError,ValueError): continue
            flows.append({'token':log.get('address','').lower(),'from':'0x'+topics[1][-40:].lower(),'to':'0x'+topics[2][-40:].lower(),'amount_raw':amount})
    return sender,created,flows,native
def native_flows(context, tx):
    pre_rows=load(Path(context)/'prestates.json'); post_rows=load(Path(context)/'poststates.json')
    post_row=next((x for x in post_rows if str(x.get('tx_hash','')).lower()==tx.lower()), None)
    pre_row=next((x for x in pre_rows if str(x.get('tx_hash','')).lower()==tx.lower()), None)
    if not post_row or not pre_row: return []
    delta=committed_native_delta(pre_row,post_row)
    # Balance deltas are committed; use them as ETH ledger legs. WETH is an
    # ERC-20 and is intentionally handled only by Transfer logs.
    return [{'token':'eth','from':a if v<0 else '0x'+'0'*40,
             'to':a if v>0 else '0x'+'0'*40,'amount_raw':abs(v)} for a,v in delta.items()]
def main():
    man=load(MAN)['cases']; b2={x['case_id']:x for x in load(B2)['cases']}
    assert len(man)==20 and set(b2)=={x['case_id'] for x in man}
    rows=[]
    for c in man:
        cid,tx=c['case_id'],c['tx_hash']; context=b2[cid]['context']; target=target_row(context,tx)
        if not target:
            rows.append({'case_id':cid,'status':'UNKNOWN','reason_code':'TARGET_TRACE_MISSING'}); continue
        sender,created,erc,native=extract(target)
        committed=native_flows(context,tx)
        infra=set(load(INF).get('wrappers',[])) | set(load(INF).get('precompiles',[])) | {load(INF).get('zero',''),load(INF).get('burn','')}
        obs=t0(erc+committed,sender,created,complete=True,infrastructure=infra).json()
        attackers=set(obs['attacker_addresses']); protected=set(obs['protected_addresses'])
        obs['harm_vector']=from_flows(erc+committed,attackers,protected).json()
        obs.update({'case_id':cid,'tx_hash':tx,'source_context':context,
                    'erc20_flow_count':len(erc),'native_flow_count':len(native),
                    'native_flow_authority':'COMMITTED_B2_PRE_POST_BALANCE_DELTA',
                    'created_contracts':created,
                    'created_contracts_authority':'ATTACKER_ANCESTRY_FROM_TRACE',
                    'provisional_t0_status':obs['status'],
                    'evidence_quality':'ERC20_COMMITTED_LOGS_ONLY',
                    'boundary_source':'automatic_complement_only'})
        rows.append(obs)
    meta=assert_frozen20([x['case_id'] for x in man], 'frozen-20')
    OUT.write_text(json.dumps({'schema_version':2,'scope':'fixed-20 factual T0 audit',**meta,
        'resolver_versions':{'run_select':'v1','attacker_set':'v2','native_ledger':'v1','harm':'t0-v2'},
        'case_count':20,'reviewer_boundary_used':False,'causal_replay_executed':False,'cases':rows},indent=2)+'\n')
    from collections import Counter
    print(json.dumps({'cases':20,'status_counts':dict(Counter(x['status'] for x in rows))},indent=2))
if __name__=='__main__': main()
