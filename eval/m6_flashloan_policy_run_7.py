"""Run the new prioritization policy over the seven B2-accepted cases."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
 q=json.loads((ROOT/'eval/results/m6_flashloan_priority_queue.json').read_text())
 rows=[r for r in q['cases'] if r.get('b2')=='PASS']
 rows.sort(key=lambda r:(r['priority_rank'],r['name']))
 for i,r in enumerate(rows,1): r['policy_order']=i; r['policy_decision']='PLANNING_ONLY_HARM_GATE_REQUIRED'
 out=ROOT/'eval/results/m6_flashloan_policy_run_7.json'
 out.write_text(json.dumps({'schema_version':1,'scope':'seven B2-accepted supplementary cases','policy':'mechanism-family priority; no causal execution','case_count':len(rows),'cases':rows},indent=2)+'\n')
 print(json.dumps([{'order':r['policy_order'],'name':r['name'],'family':r['mechanism_family'],'plans':r['planned_mutations'],'decision':r['policy_decision']} for r in rows],indent=2))
if __name__=='__main__':main()
