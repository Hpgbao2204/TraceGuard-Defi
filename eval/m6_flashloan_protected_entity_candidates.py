"""Rank protected-entity candidates from raw Transfer-flow ledgers.

Exploratory only: this never assigns harm or causal verdicts.
"""
import json
from collections import defaultdict
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
def main():
 data=json.loads((ROOT/'eval/results/m6_flashloan_harm_flow_batch.json').read_text())
 rows=[]
 for item in data.get('cases',[]):
  by=defaultdict(lambda: defaultdict(int))
  for f in item.get('flows',[]):
   t=f['token'].lower(); a=f['from'].lower(); b=f['to'].lower(); n=int(f['amount_raw'])
   by[t][a]-=n; by[t][b]+=n
  candidates=[]
  for token, balances in by.items():
   for address, delta in balances.items():
    if delta < 0:
     candidates.append({'token':token,'address':address,'net_delta_raw':str(delta),'abs_delta_raw':str(-delta)})
  candidates.sort(key=lambda x:int(x['abs_delta_raw']), reverse=True)
  rows.append({'case':item.get('case') or item.get('name'),'status':'CANDIDATES_ONLY','candidate_count':len(candidates),'candidates':candidates[:20], 'policy_note':'ranked from Transfer ledger only; protected identity and flash-loan round-trip not adjudicated'})
 out=ROOT/'eval/results/m6_flashloan_protected_entity_candidates.json'
 out.write_text(json.dumps({'schema_version':1,'scope':'exploratory protected-entity screening; no harm verdict','cases':rows},indent=2)+'\n')
 print(json.dumps([{'case':r['case'],'top':r['candidates'][:3]} for r in rows],indent=2))
if __name__=='__main__':main()
