"""Run raw T0 on all 80; fidelity failures remain UNKNOWN fail-closed."""
import csv,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from eval.m6_harm_v2 import t0
from core.env import load_dotenv,resolve_rpc
from core.rpc import RpcClient
POOL=ROOT/'eval/results/e5_rcfh/defihacklabs_t0_candidate_pool.json'
FID=ROOT/'eval/results/e5_rcfh/defihacklabs_80_fidelity.csv'
OUT=ROOT/'eval/results/e5_rcfh/defihacklabs_80_t0_raw.json'
TOPIC='0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef'
def main():
 load_dotenv(); rpc=RpcClient(resolve_rpc('ethereum'),timeout=20,attempts=2)
 pool={x['candidate_id']:x for x in json.loads(POOL.read_text())['candidates']}
 fid={r['case']:r for r in csv.DictReader(FID.open())}; rows=[]
 for cid,p in pool.items():
  f=fid[cid]; base={'case_id':cid,'tx_hash':f['tx_hash'],'fidelity_outcome':f['outcome'],'t0_status':'UNKNOWN','hard_deltas':{},'reason':'fidelity_not_accepted'}
  if f['outcome']!='EXECUTED_UNKNOWN' or f.get('execution_pass')!='True': rows.append(base); continue
  try:
   tx=rpc.eth_get_transaction(f['tx_hash']); rec=rpc.eth_get_receipt(f['tx_hash']); flows=[]
   for log in (rec or {}).get('logs',[]):
    topics=log.get('topics',[])
    if topics and topics[0].lower()==TOPIC and len(topics)>=3:
     flows.append({'token':log['address'].lower(),'from':'0x'+topics[1][-40:].lower(),'to':'0x'+topics[2][-40:].lower(),'amount_raw':int(log['data'],16)})
   value=int((tx or {}).get('value','0x0'),16)
   if value: flows.append({'token':'eth','from':tx['from'].lower(),'to':(tx.get('to') or '0x'+'0'*40).lower(),'amount_raw':value})
   obs=t0(flows,tx.get('from'),[],complete=bool(rec))
   base.update(t0_status=obs.status,hard_deltas=obs.json()['hard_deltas'],reason=obs.reason_code or 'raw_receipt_flow',flow_count=len(flows),protected_addresses=obs.json()['protected_addresses'])
  except Exception as e: base.update(reason='t0_acquisition_error:'+str(e).split('?',1)[0])
  rows.append(base)
 counts={}
 for r in rows: counts[r['t0_status']]=counts.get(r['t0_status'],0)+1
 out={'schema_version':1,'artifact':'defihacklabs-80-t0-raw-v1','scope':'raw receipt-flow T0 only; no protected-entity gold labels','case_count':80,'counts':counts,'cases':rows,'policy':'fidelity failure is UNKNOWN; receipt-flow T0 does not establish protocol-scoped harm or causal harm.'}
 OUT.write_text(json.dumps(out,indent=2,sort_keys=True)+'\n'); print(json.dumps(counts,indent=2))
if __name__=='__main__': main()
