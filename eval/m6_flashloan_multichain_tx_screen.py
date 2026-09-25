"""Read-only multi-chain availability gate for the proposed candidate hashes."""
import json, urllib.request
from pathlib import Path

CASES = {
 "Clober DEX": ("ethereum", "0x8fcdfcded45100437ff94801090355f2f689941dca75de9a702e01670f361c04"),
 "UtopiaSphere": ("bsc", "0x1ddf415a4b18d25e87459ad1416077fe7398d5504171d4ca36e757b1a889f604"),
 "Palmswap": ("bsc", "0x62dba55054fa628845fecded658ff5b1ec1c5823f1a5e0118601aa455a30eac9"),
 "Radiant Capital": ("arbitrum", "0x1ce7e9a9e3b6dd3293c9067221ac3260858ce119ecb7ca860eac28b2474c7c9b"),
 "Sonne Finance": ("optimism", "0x45c0ccfd3ca1b4a937feebcb0f5a166c409c9e403070808835d41da40732db96"),
 "Onyx Protocol": ("ethereum", "0xf7c21600452939a81b599017ee24ee0dfd92aaaccd0a55d02819a7658a6ef635"),
 "Bao Finance": ("ethereum", "0xdd7dd68cd879d07cfc2cb74606baa2a5bf18df0e3bda9f6b43f904f4f7bbdfc1"),
 "PancakeBunny": ("bsc", "0x897c2de73dd55d7701e1b69ffb3a17b0f4801ced88b0c75fe1551c5fcce6a979"),
 "Platypus Finance": ("avalanche", "0x1266a937c2ccd970e5d7929021eed3ec593a95c68a99b4920c2efa226679b430"),
 "OSN": ("bsc", "0xc7927a68464ebab1c0b1af58a5466da88f09ba9b30e6c255b46b1bc2e7d1bf09"),
 "TLN/VOW/VUSD": ("bsc", "0x1350cc72865420ba5d3c27234fd4665ad25c021b0a75ba03bc8340a1b1f98a45"),
 "TCH": ("bsc", "0xa94338d8aa312ed4b97b2a4dcb27f632b1ade6f3abec667e3bf9f002a75dabe0"),
}
ENV = {"ethereum":"ARCHIVE_RPC", "bsc":"QUICKNODE_BNB", "arbitrum":"ARB_ARCHIVE_RPC", "optimism":"QUICKNODE_OPT", "base":"ANKR_BASE", "avalanche":"ANKR_AVAX"}
def main():
 env={}
 for l in (Path(__file__).parents[1]/'.env').read_text().splitlines():
  if '=' in l: k,v=l.split('=',1); env[k]=v.strip().strip('"').strip("'")
 def call(url,m,p):
  req=urllib.request.Request(url,data=json.dumps({'jsonrpc':'2.0','id':1,'method':m,'params':p}).encode(),headers={'content-type':'application/json'})
  with urllib.request.urlopen(req,timeout=30) as res:return json.load(res).get('result')
 rows=[]
 for name,(chain,h) in CASES.items():
  url=env.get(ENV[chain]); row={'name':name,'chain':chain,'tx_hash':h}
  if not url: row['status']='NO_CONFIGURED_RPC'
  else:
   try:
    tx=call(url,'eth_getTransactionByHash',[h]); row['status']='FOUND' if tx else 'NOT_FOUND';
    if tx: row.update({'block':int(tx['blockNumber'],16),'tx_index':int(tx['transactionIndex'],16),'receipt_status':int((call(url,'eth_getTransactionReceipt',[h]) or {})['status'],16)})
   except Exception as exc: row.update({'status':'RPC_ERROR','error_type':type(exc).__name__})
  rows.append(row); print(row)
 p=Path(__file__).parents[1]/'eval/results/m6_flashloan_multichain_tx_screen.json'; p.write_text(json.dumps({'schema_version':1,'status':'CHAIN_GATE_ONLY','cases':rows},indent=2)+'\n')
if __name__=='__main__':main()
