"""Apply the supplementary mechanism-priority policy to current candidates."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
ORDER={'access-control':0,'input-validation':0,'reentrancy':1,'business-logic':2,'accounting':3,'oracle':4,'unknown':5}
FAMILY={'Dough Finance':'input-validation','Clober DEX':'reentrancy','XPEPE':'access-control','UtopiaSphere':'oracle','Palmswap':'business-logic','Radiant Capital':'accounting','Sonne Finance':'accounting','Onyx Protocol':'accounting','Euler Finance':'business-logic','Indexed Finance':'oracle','Paribus':'reentrancy','Bao Finance':'accounting','FEG Token':'input-validation','OSN':'accounting','TLN/VOW/VUSD':'accounting','TCH':'access-control','Harvest Finance':'oracle','PancakeBunny':'oracle','KyberSwap Elastic':'oracle','Platypus Finance':'business-logic'}
def family(name):
 n=name.lower()
 if any(x in n for x in ('signature','allowance','access','auth','validation')): return 'access-control' if 'auth' in n or 'signature' in n or 'allowance' in n else 'input-validation'
 if 'reentr' in n: return 'reentrancy'
 if any(x in n for x in ('oracle','reserve','price','kyber')): return 'oracle'
 if any(x in n for x in ('account','share','reward','euler','indexed','harvest','bao')): return 'accounting'
 return 'unknown'
def main():
 matrix=json.loads((ROOT/'eval/results/m6_flashloan_20_status_matrix.json').read_text())
 plans=json.loads((ROOT/'eval/results/m6_flashloan_e4_plan_batch.json').read_text())
 pm={x['name']:x for x in plans.get('cases',[])}
 rows=[]
 for x in matrix['cases']:
  f=FAMILY.get(x['name'],family(x['name'])); p=pm.get(x['name'],{})
  rows.append({**x,'mechanism_family':f,'priority_rank':ORDER[f],'planned_mutations':len(p.get('mutations',[])),'priority_status':'READY_FOR_HARM_AND_E4' if x['b2']=='PASS' and p.get('mutations') else ('B2_READY_NO_SUPPORTED_PLAN' if x['b2']=='PASS' else 'NOT_READY')})
 rows.sort(key=lambda x:(x['priority_rank'],x['name']))
 out=ROOT/'eval/results/m6_flashloan_priority_queue.json'; out.write_text(json.dumps({'schema_version':1,'scope':'supplementary; prioritization only','causal_replay_executed':False,'cases':rows},indent=2)+'\n')
 print(json.dumps([{'name':x['name'],'family':x['mechanism_family'],'b2':x['b2'],'status':x['priority_status'],'plans':x['planned_mutations']} for x in rows],indent=2))
if __name__=='__main__':main()
