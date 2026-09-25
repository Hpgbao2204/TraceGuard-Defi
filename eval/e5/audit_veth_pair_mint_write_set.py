#!/usr/bin/env python3
import hashlib, json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/'eval/results/m4/b2-contexts-fresh/defihacklabs-veth-2024-11-14'
OUT=ROOT/'eval/results/e5_rcfh/veth_buyquote_dose_probe/pair_mint_write_set_audit.json'
ADDRESSES={
 'pair':'0x582d17d24127cfdcbc8c4e0a40c12d77b2e7a48d',
 'virtual_token':'0x280a8955a11fcd81d72ba1f99d265a48ce39ac2e',
 'lambo_token':'0xab181941a6096296ecf1b0859ea65c797676d428',
}
def main():
 pre=json.loads((BASE/'prestates.json').read_text())[57]['trace']; post=json.loads((BASE/'poststates.json').read_text())[57]['poststate']
 diffs={}
 for name,addr in ADDRESSES.items():
  a=pre.get(addr,{}).get('storage',{}); b=post.get(addr,{}).get('storage',{})
  diffs[name]=[{'slot':k,'before':a.get(k),'after':b.get(k)} for k in sorted(set(a)|set(b)) if a.get(k)!=b.get(k)]
 out={'status':'PAIR_MINT_WRITE_SET_OBSERVED_TRANSACTION_SCOPE_ONLY','case_id':'defihacklabs-veth-2024-11-14','observed_transaction_storage_diffs':diffs,'confirmed_helper_pair_mint_write_set':None,'interpretation':'The authenticated target transaction changes multiple pair/token storage cells. The available opcode tail and pre/post diff do not isolate writes executed specifically by pair.mint at trace 54 from writes caused by primary/reverse swaps and token bookkeeping. Reserve state is not the only observed changed state; do not construct a StoragePatchAtCallSite from the whole transaction diff. A helper-local write-set requires frame-scoped SSTORE telemetry or verified source/bytecode semantic attribution.','required_next_telemetry':['frame-scoped SSTORE events with storage-context address and slot/value','pair.mint entry/exit delimitation','mapping-slot attribution if LP balances or kLast are included'],'prestate_sha256':hashlib.sha256((BASE/'prestates.json').read_bytes()).hexdigest(),'poststate_sha256':hashlib.sha256((BASE/'poststates.json').read_bytes()).hexdigest()}
 OUT.write_text(json.dumps(out,indent=2)+'\n'); print(OUT); print(hashlib.sha256(OUT.read_bytes()).hexdigest())
if __name__=='__main__': main()
