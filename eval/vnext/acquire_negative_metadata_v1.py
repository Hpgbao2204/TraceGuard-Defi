"""Metadata-only ordinary-negative acquisition; no tracing or model scores."""
from __future__ import annotations
import argparse, hashlib, json, os, random, time, urllib.error, urllib.request, socket
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
SEED=20260916
class RetryExhausted(RuntimeError): pass
class TransportFailure(RuntimeError): pass
def rpc(url,method,params):
    body=json.dumps({'jsonrpc':'2.0','id':1,'method':method,'params':params}).encode(); req=urllib.request.Request(url,data=body,headers={'content-type':'application/json'})
    try:
        with urllib.request.urlopen(req,timeout=12) as r: d=json.loads(r.read())
    except (socket.timeout, TimeoutError) as e: raise TransportFailure('CONNECT_OR_READ_TIMEOUT') from e
    except urllib.error.URLError as e: raise TransportFailure('TRANSPORT_ERROR') from e
    if d.get('error'): raise RuntimeError(str(d['error'])[:200])
    return d.get('result')
def gid(chain,to,sel,tx=None):
    if to: raw=f'{chain}|{to.lower()}|{sel.lower()}'
    else: raw=f'{chain}|{tx.get("from","unknown").lower()}|{hashlib.sha256((tx.get("input") or "0x").encode()).hexdigest()}'
    return hashlib.sha256(raw.encode()).hexdigest()
def fetch(url,method,params,attempts=4):
    last=None
    for i in range(attempts):
        started=time.monotonic()
        try: return rpc(url,method,params)
        except Exception as e:
            last=e
            print(f'transport method={method} attempt={i+1}/{attempts} elapsed={time.monotonic()-started:.2f}s error={type(e).__name__}:{e}',flush=True)
            if i+1<attempts:
                h=getattr(e,'headers',{})
                ra=h.get('Retry-After') if h else None
                time.sleep(min(30,float(ra)) if ra and ra.isdigit() else min(30,2**i))
    raise RetryExhausted(str(last))
def atomic_json(path,obj):
    tmp=path.with_suffix(path.suffix+'.tmp'); tmp.write_text(json.dumps(obj,indent=2,sort_keys=True)+'\n'); tmp.replace(path)
def load_hashes(path, fields=('tx_hash','tx_hashes')):
    found=set()
    if not path.exists(): return found
    for line in path.read_text().splitlines():
        if not line.strip(): continue
        try: x=json.loads(line)
        except json.JSONDecodeError: continue
        for f in fields:
            v=x.get(f,[])
            if isinstance(v,str): v=[v]
            found.update(str(h).lower() for h in v)
    return found
def largest_remainder(counts,target):
    total=sum(counts.values()) or 1
    raw={k:target*v/total for k,v in counts.items()}
    q={k:int(v) for k,v in raw.items()}; left=target-sum(q.values())
    for k,_ in sorted(raw.items(),key=lambda kv:(kv[1]-int(kv[1]),str(kv[0])),reverse=True)[:left]: q[k]+=1
    return q
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--target',type=int,default=4000); ap.add_argument('--blocks-per-chain',type=int,default=40); ap.add_argument('--chain',choices=['ethereum','bsc','arbitrum','optimism']); ap.add_argument('--smoke',action='store_true'); ap.add_argument('--checkpoint-every',type=int,default=25); args=ap.parse_args()
    for l in (ROOT/'.env').read_text().splitlines():
        if '=' in l:
            k,v=l.split('=',1); os.environ.setdefault(k,v.strip("'\""))
    urls={'ethereum':os.getenv('ARCHIVE_RPC'),'bsc':os.getenv('QUICKNODE_BNB'),'arbitrum':os.getenv('ARB_ARCHIVE_RPC'),'optimism':os.getenv('QUICKNODE_OPT')}
    meta=ROOT/'eval/vnext/positives/positive_metadata_v1.jsonl'
    manifest=json.loads((ROOT/'eval/vnext/positives/positive_metadata_manifest_v1.json').read_text())
    if manifest.get('status')!='READY' or manifest.get('materialized')!=144: raise SystemExit('REFUSE: positive metadata is not READY 144/144')
    positives=[json.loads(x) for x in meta.read_text().splitlines() if x.strip()]
    excluded=load_hashes(ROOT/'corpus/vnext/positive_registry.jsonl')
    excluded |= load_hashes(ROOT/'corpus/incidents.jsonl')
    excluded |= load_hashes(ROOT/'corpus/vnext/hard_negative_candidates.jsonl')
    excluded |= load_hashes(ROOT/'corpus/vnext/hard_negative_pilot_review_queue.jsonl')
    excluded |= load_hashes(ROOT/'corpus/vnext/hard_negative_pilot_adjudication_queue.jsonl')
    rng=random.Random(SEED); rows=[]; seen=set(); failures=[]
    out=ROOT/'eval/vnext/negatives/negative_metadata_candidates_v1.jsonl'; out.parent.mkdir(parents=True,exist_ok=True)
    if args.smoke: out=out.parent/'negative_metadata_smoke.jsonl'
    cursor_path=out.with_name(out.stem+'.cursor.json')
    cursor=json.loads(cursor_path.read_text()) if cursor_path.exists() else {}
    if out.exists():
        for line in out.read_text().splitlines():
            if line.strip():
                x=json.loads(line); rows.append(x); seen.add(x['tx_hash'].lower())
    anchor_by_chain={c:[x for x in positives if x.get('chain')==c] for c in urls}
    buckets={c:{} for c in urls}
    for c,xs in anchor_by_chain.items():
        for x in xs:
            b=int(x['timestamp'])//(90*86400); buckets[c][b]=buckets[c].get(b,0)+1
    total=sum(sum(v.values()) for v in buckets.values()) or 1
    quotas=largest_remainder({(c,b):n for c,bs in buckets.items() for b,n in bs.items()},args.target)
    if args.chain: urls={args.chain:urls[args.chain]}
    checkpoint_every=args.checkpoint_every; blocks_done=0; stratum_counts={}
    for x in rows: stratum_counts[(x['chain'],x['timestamp']//(90*86400))]=stratum_counts.get((x['chain'],x['timestamp']//(90*86400)),0)+1
    def chain_complete(c):
        return all(stratum_counts.get((c,b),0) >= q for (cc,b),q in quotas.items() if cc==c)
    for chain,url in urls.items():
        if not url: failures.append({'chain':chain,'reason':'RPC_NOT_CONFIGURED'}); continue
        chainpos=anchor_by_chain[chain]
        blocks=sorted({int(x['block_number']) for x in chainpos if x.get('block_number')})
        if not blocks: failures.append({'chain':chain,'reason':'NO_POSITIVE_BLOCK_ANCHOR'}); continue
        if chain_complete(chain):
            continue
        candidates=[]
        for b in blocks:
            candidates.extend(max(0,b-i) for i in range(1,args.blocks_per_chain+1))
        rng.shuffle(candidates)
        start=int(cursor.get(chain,{}).get('candidate_index',0))
        for candidate_index,block in enumerate(candidates):
            if candidate_index < start: continue
            atomic_json(cursor_path,{**cursor,chain:{'candidate_index':candidate_index,'last_block':block,'rows':len(rows)}})
            try:
                print(f'progress chain={chain} candidate={candidate_index}/{len(candidates)} block={block} accepted={len(rows)}',flush=True)
                result=fetch(url,'eth_getBlockByNumber',[hex(block),True])
                if not result: continue
                ts=int(result.get('timestamp','0x0'),16); bh=result.get('hash')
                bucket=ts//(90*86400); key=(chain,bucket)
                if quotas.get(key,0)==0 or stratum_counts.get(key,0)>=quotas.get(key,0):
                    continue
                for idx,tx in enumerate(result.get('transactions') or []):
                    h=tx.get('hash'); to=tx.get('to'); inp=tx.get('input') or '0x'; sel=inp[:10] if len(inp)>=10 else '0x'
                    if not h or h.lower() in excluded or h.lower() in seen: continue
                    receipt=fetch(url,'eth_getTransactionReceipt',[h])
                    if not receipt or receipt.get('status') not in ('0x1',1): continue
                    onchain_idx=int(tx.get('transactionIndex','0x0'),16)
                    if onchain_idx != idx or receipt.get('blockHash') != bh or tx.get('blockHash') != bh:
                        failures.append({'chain':chain,'block':block,'tx_hash':h,'reason':'METADATA_CROSSCHECK_FAILED'}); continue
                    if stratum_counts.get(key,0)>=quotas.get(key,0): break
                    seen.add(h.lower()); rows.append({'tx_hash':h,'label':0,'negative_tier':'ordinary','chain':chain,'block_number':block,'block_hash':bh,'tx_index':idx,'timestamp':ts,'receipt_status':receipt.get('status'),'to':to,'top_level_selector':sel,'group_id':gid(chain,to,sel,tx),'stratum':f'{chain}|{bucket}','sampling_seed':SEED,'provenance_status':'METADATA_RECEIPT_VERIFIED','source':'fresh_block_sampling_v1'})
                    stratum_counts[key]=stratum_counts.get(key,0)+1
                    if len(rows)>=args.target: break
                if len(rows)>=args.target: break
            except RetryExhausted as exc:
                failures.append({'chain':chain,'block':block,'reason':'RETRY_EXHAUSTED','action':'CHECKPOINT_AND_STOP'}); break
            except Exception as exc: failures.append({'chain':chain,'block':block,'reason':str(exc)[:160]})
            blocks_done+=1
            if blocks_done % checkpoint_every == 0:
                out.write_text(''.join(json.dumps(x,sort_keys=True)+'\n' for x in rows))
                print(f'progress chain={chain} block={block} bucket={bucket} quota={quotas.get(key,0)} current={stratum_counts.get(key,0)} accepted={len(rows)}',flush=True)
            atomic_json(cursor_path,{**cursor,chain:{'candidate_index':candidate_index+1,'last_block':block,'rows':len(rows)}})
        if len(rows)>=args.target or (failures and failures[-1].get('reason')=='RETRY_EXHAUSTED'): break
    out.write_text(''.join(json.dumps(x,sort_keys=True)+'\n' for x in rows)); summary={'schema_version':1,'policy':'negative-sampling-v1','status':'CANDIDATES_READY_FOR_FREEZE' if len(rows)>=args.target else 'INCOMPLETE_RETRYABLE','target':args.target,'rows':len(rows),'unique_hashes':len(seen),'failures':failures,'sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'smoke':args.smoke}; (out.parent/('negative_metadata_smoke_summary_v1.json' if args.smoke else 'negative_metadata_acquisition_summary_v1.json')).write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n'); print(json.dumps(summary,indent=2,sort_keys=True))
if __name__=='__main__': main()
