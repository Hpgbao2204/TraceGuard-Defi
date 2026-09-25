"""Acquire callTracer traces for the frozen negative registry, resumably."""
import argparse,json,os,time,urllib.request,urllib.error,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
URL_ENV={'ethereum':'ARCHIVE_RPC','bsc':'QUICKNODE_BNB','arbitrum':'QUICKNODE_ARB','optimism':'QUICKNODE_OPT'}
def complete(x): return bool(x.get('trace')) and x.get('receipt_status') in ('0x1',1) and 'receipt_logs' in x
def rpc(url,method,params):
 b=json.dumps({'jsonrpc':'2.0','id':1,'method':method,'params':params}).encode(); req=urllib.request.Request(url,data=b,headers={'content-type':'application/json'})
 with urllib.request.urlopen(req,timeout=30) as r: d=json.loads(r.read())
 if d.get('error'): raise RuntimeError(str(d['error'])[:200])
 return d.get('result')
def fetch(url,method,params,attempts=4):
 last=None
 for i in range(attempts):
  try: return rpc(url,method,params)
  except Exception as e:
   last=e
   if i+1<attempts: time.sleep(min(30,2**i))
 raise RuntimeError(f'RETRY_EXHAUSTED:{method}:{last}')
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--chain',choices=list(URL_ENV)); ap.add_argument('--limit',type=int); args=ap.parse_args()
 for l in (ROOT/'.env').read_text().splitlines():
  if '=' in l: k,v=l.split('=',1); os.environ.setdefault(k,v.strip("'\""))
 rows=[json.loads(x) for x in (ROOT/'eval/vnext/negatives/negative_registry_v1.jsonl').read_text().splitlines() if x.strip()]
 if args.chain: rows=[x for x in rows if x['chain']==args.chain]
 out=ROOT/'eval/vnext/acquisition/negative_trace_cache.jsonl'; out.parent.mkdir(parents=True,exist_ok=True)
 cached={json.loads(x)['tx_hash']:json.loads(x) for x in out.read_text().splitlines() if x.strip()} if out.exists() else {}
 done={h for h,x in cached.items() if complete(x)}
 rows=[x for x in rows if x['tx_hash'] not in done]
 if args.limit: rows=rows[:args.limit]
 failures=[]
 for i,x in enumerate(rows,1):
  url=os.getenv(URL_ENV[x['chain']]);
  if not url: raise SystemExit('RPC_NOT_CONFIGURED:'+x['chain'])
  try:
   trace=fetch(url,'debug_traceTransaction',[x['tx_hash'],{'tracer':'callTracer'}])
   receipt=fetch(url,'eth_getTransactionReceipt',[x['tx_hash']])
   if not receipt or receipt.get('status') not in ('0x1',1): raise RuntimeError('RECEIPT_NOT_SUCCESS')
   cached[x['tx_hash']]= {**x,'source':'callTracer','trace':trace,'receipt_logs':receipt.get('logs',[]),'receipt_status':receipt.get('status')}
   out.write_text(''.join(json.dumps(v,sort_keys=True)+'\n' for v in cached.values()))
   print(f'progress {x["chain"]} {i}/{len(rows)} {x["tx_hash"]}',flush=True)
  except Exception as e:
   failures.append({'tx_hash':x['tx_hash'],'chain':x['chain'],'rpc_method':'debug_traceTransaction/eth_getTransactionReceipt','error_class':str(e)[:200],'retryable':'RETRY_EXHAUSTED' in str(e),'attempts':4})
 (out.parent/'negative_trace_failures_v1.jsonl').write_text(''.join(json.dumps(v,sort_keys=True)+'\n' for v in failures))
 complete_total=sum(complete(x) for x in cached.values()); summary={'registry_rows':4000,'requested_now':len(rows),'succeeded_now':len(rows)-len(failures),'failed_now':len(failures),'complete_total':complete_total,'incomplete_total':4000-complete_total,'cache':str(out),'status':'COMPLETE' if complete_total==4000 else 'INCOMPLETE_RETRYABLE'}
 (out.parent/'negative_trace_acquisition_summary_v1.json').write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n'); print(json.dumps(summary,indent=2,sort_keys=True))
if __name__=='__main__': main()
