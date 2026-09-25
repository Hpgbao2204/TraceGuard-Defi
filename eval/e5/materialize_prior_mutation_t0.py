"""Materialize comparable T0 ERC20 vectors from prior B2 mutation outputs."""
from __future__ import annotations
import json
from pathlib import Path
from eval.m6_harm_v2 import t0
from eval.attacker_set_v2 import derive
from eval.e4.harm_vector import from_flows

ROOT=Path(__file__).resolve().parents[2]
TOPIC='0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef'
FIXED20_HARM = ROOT / 'eval/results/m6_harm_detection_v2_fixed20_t0.json'

def cases_with_existing_mutations():
 data = json.loads(FIXED20_HARM.read_text())
 out = {}
 for item in data.get('cases', []):
  if item.get('status') != 'HARM':
   continue
  case = item['case_id']
  run_dir = ROOT / 'eval/results/runs' / f'm6-b2-{case}'
  muts = sorted(p.name[len('b2-mutation-'):-len('.json')]
                for p in run_dir.glob('b2-mutation-*.json'))
  out[case] = {'declared_status': item.get('status'), 'mutations': muts}
 return out

def flows(row):
 out=[]
 for log in row.get('logs') or []:
  topics=log.get('topics') or []
  if len(topics)>=3 and topics[0].lower()==TOPIC:
   out.append({'token':log['address'].lower(),'from':'0x'+topics[1][-40:].lower(),'to':'0x'+topics[2][-40:].lower(),'amount_raw':int(log.get('data','0x0'),16)})
 return out

def one(path):
 d=json.loads(path.read_text()); row=d['per_tx'][int(d['target_index'])]
 trace=row.get('call_trace') or []; root=next(x for x in trace if x.get('event')=='enter' and x.get('depth')==0)
 attacker,created=derive(trace,root.get('from')); fs=flows(row)
 obs=t0(fs,root.get('from'),created,complete=True,infrastructure=set()).json()
 obs['harm_vector']=from_flows(fs,set(obs['attacker_addresses']),set(obs['protected_addresses'])).json()
 return {'execution':{'status':row.get('actual_status'),'gas_match':row.get('gas_match'),'status_match':row.get('status_match'),'logs_match':row.get('logs_match'),'post_state_match':row.get('post_state_match')},'observed_asset_domain':'ERC20 Transfer logs only','native_observation':'MISSING','t0':obs}

def main():
 out=[]
 cases = cases_with_existing_mutations()
 for case, selection in cases.items():
  muts = selection['mutations']
  base=ROOT/'eval/results/runs'/f'm6-b2-{case}'/'b2-baseline.json'
  item={'case_id':case,'declared_fixed20_baseline_status':selection['declared_status'],'baseline':one(base) if base.exists() else {'status':'MISSING_BASELINE_ARTIFACT'},'mutations':{}}
  for m in muts:
   p=ROOT/'eval/results/runs'/f'm6-b2-{case}'/f'b2-mutation-{m}.json'
   item['mutations'][m]=one(p) if p.exists() else {'status':'MISSING'}
  item['classification']='PARTIAL_T0_VECTOR_NO_NATIVE'
  out.append(item)
 dest=ROOT/'eval/results/e5_rcfh/prior_mutation_t0_materialization.json'; dest.write_text(json.dumps({'schema_version':4,'artifact':'e5-prior-mutation-t0-materialization','selection':{'source':'m6_harm_detection_v2_fixed20_t0.json','criterion':'all baseline status HARM cases; mutation list is empty when no artifact exists'},'policy':'ERC20 vectors are diagnostic only when the committed harm domain is incomplete. Intervention gas/post-state differences are recorded diagnostics, not automatic invalidation; admissibility requires a same-kind sham, semantic seam validation, execution reaching the observation point, and a committed ledger for the declared harm domain. No causal verdict is emitted here.','cases':out},indent=2)+'\n')
 print(json.dumps({'fixed20_declared_harm_cases':len(out),'cases_with_mutations':sum(bool(x['mutations']) for x in out),'cases_without_mutations':sum(not x['mutations'] for x in out),'mutations':sum(len(x['mutations']) for x in out),'status':'MATERIALIZED_PARTIAL'},indent=2))
if __name__=='__main__': main()
