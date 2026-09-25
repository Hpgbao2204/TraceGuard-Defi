"""Scan unresolved candidate hashes across configured chain RPCs."""
import json, os, urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
HASHES={
'Clober DEX':'0x8fcdfcded45100437ff94801090355f2f689941dca75de9a702e01670f361c04',
'Paribus':'0x0e29dcf4e9b211a811caf8fc8294024867bffe4ab2819cc1625d2e9d62390af',
'FEG Token':'0x77cf448ceaf8f66e06d1537ef83218725670d3a509583ea0d161533fda56c063',
'Platypus Finance':'0x1266a937c2ccd970e5d7929021eed3ec593a95c68a99b4920c2efa226679b430'}
ENVS={'ethereum':'ARCHIVE_RPC','bsc':'QUICKNODE_BNB','arbitrum':'ARB_ARCHIVE_RPC','optimism':'QUICKNODE_OPT','avalanche':'ANKR_AVAX'}
def main():
 env={};
 for line in (ROOT/'.env').read_text().splitlines():
  if '=' in line:
   k,v=line.split('=',1); env[k]=v.strip().strip('"').strip("'")
 def call(url,method,params):
  req=urllib.request.Request(url,data=json.dumps({'jsonrpc':'2.0','id':1,'method':method,'params':params}).encode(),headers={'content-type':'application/json'})
  with urllib.request.urlopen(req,timeout=25) as r:return json.load(r).get('result')
 rows=[]
 for name,h in HASHES.items():
  hits=[]
  for chain,key in ENVS.items():
   u=env.get(key)
   if not u: continue
   try:
    tx=call(u,'eth_getTransactionByHash',[h])
    if tx: hits.append({'chain':chain,'block':int(tx['blockNumber'],16),'tx_index':int(tx['transactionIndex'],16)})
   except Exception as e: pass
  rows.append({'name':name,'tx_hash':h,'hits':hits,'status':'FOUND_ON_CHAIN' if hits else 'NOT_FOUND_CONFIGURED_CHAINS'})
 out=ROOT/'eval/results/m6_flashloan_missing_hash_chain_scan.json'; out.write_text(json.dumps({'schema_version':1,'scope':'identity scan only','cases':rows},indent=2)+'\n'); print(json.dumps(rows,indent=2))
if __name__=='__main__':main()
