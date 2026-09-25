"""Read-only historical token-flow and balance observations for Giddy."""
import json, os, urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
TX='0x5edb66a4c2ea55bba95d36d27713e3bb1c67c3c4199a8a1759e754c6f25482e5'
ENTITIES={
 '0xc99fc715e73294fd03b7c09d9a438a98f6c76ec3':'tBTC strategy',
 '0x0d5e628a44e7ec94a2054a6c454127cfe5fcb690':'cbBTC strategy',
 '0x870fcd63db2c68d8079166e311b1118b8aa26ed7':'WBTC strategy',
}
def main():
 for l in (ROOT/'.env').read_text().splitlines():
  if l.startswith('ARCHIVE_RPC='): os.environ['RPC']=l.split('=',1)[1].strip().strip('"').strip("'")
 u=os.environ['RPC']
 def c(m,p):
  q=urllib.request.Request(u,data=json.dumps({'jsonrpc':'2.0','id':1,'method':m,'params':p}).encode(),headers={'content-type':'application/json'})
  with urllib.request.urlopen(q,timeout=30) as r: return json.load(r).get('result')
 tx=c('eth_getTransactionByHash',[TX]); b=int(tx['blockNumber'],16); rec=c('eth_getTransactionReceipt',[TX])
 topic='0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef'; logs=[]; tokens=set()
 for l in rec['logs']:
  if l['topics'][0].lower()==topic and len(l['topics'])>=3:
   f='0x'+l['topics'][1][-40:]; to='0x'+l['topics'][2][-40:]; token=l['address'].lower(); tokens.add(token)
   if f.lower() in ENTITIES or to.lower() in ENTITIES: logs.append({'token':token,'from':f.lower(),'to':to.lower(),'amount_raw':int(l['data'],16),'log_index':int(l['logIndex'],16)})
 observations=[]
 valuation={}
 underlying_balances=[]
 for token in sorted(tokens):
  decraw=c('eth_call',[{'to':token,'data':'0x313ce567'},hex(b-1)]); dec=None if decraw in ('0x','0x0',None) else int(decraw,16)
  nameraw=c('eth_call',[{'to':token,'data':'0x06fdde03'},hex(b-1)])
  for entity,label in ENTITIES.items():
   data='0x70a08231'+'0'*24+entity[2:]
   pre=c('eth_call',[{'to':token,'data':data},hex(b-1)]); post=c('eth_call',[{'to':token,'data':data},hex(b)])
   if pre not in ('0x','0x0',None) or post not in ('0x','0x0',None):
    before=0 if pre in ('0x','0x0',None) else int(pre,16); after=0 if post in ('0x','0x0',None) else int(post,16)
    observations.append({'entity':entity,'entity_label':label,'token':token,'decimals':dec,'before_raw':before,'after_raw':after,'delta_raw':after-before,'name_return':nameraw})
  if dec is not None:
   supplyraw=c('eth_call',[{'to':token,'data':'0x18160ddd'},hex(b-1)]); assetsraw=c('eth_call',[{'to':token,'data':'0x01e1d114'},hex(b-1)]); assetraw=c('eth_call',[{'to':token,'data':'0x38d52e0f'},hex(b-1)])
   if supplyraw not in (None,'0x','0x0') and assetsraw not in (None,'0x','0x0'):
    supply=int(supplyraw,16); assets=int(assetsraw,16)
    valuation[token]={'asset':'0x'+assetraw[-40:] if assetraw and assetraw!='0x' else None,'total_supply_raw':supply,'total_assets_raw':assets,'assets_per_share_1e18':assets*10**18//supply if supply else None}
    underlying='0x'+assetraw[-40:] if assetraw and assetraw!='0x' else None
    if underlying:
     for entity,label in ENTITIES.items():
      data='0x70a08231'+'0'*24+entity[2:]; pre=c('eth_call',[{'to':underlying,'data':data},hex(b-1)]); post=c('eth_call',[{'to':underlying,'data':data},hex(b)])
      if pre not in (None,'0x','0x0') and post not in (None,'0x','0x0'):
       underlying_balances.append({'entity':entity,'asset':underlying,'before_raw':int(pre,16),'after_raw':int(post,16),'delta_raw':int(post,16)-int(pre,16)})
 feed='0xf4030086522a5beea4988f8ca5b36dbc97bee88c'; rd=c('eth_call',[{'to':feed,'data':'0xfeaf968c'},hex(b-1)]); btc_price_1e8=int(rd[66:130],16) if rd and len(rd)>=322 else None; price_timestamp=int(rd[130:194],16) if rd and len(rd)>=322 else None
 usd_candidates=[]
 for o in observations:
  v=valuation.get(o['token'],{}).get('assets_per_share_1e18');
  if v and o['delta_raw']<0 and btc_price_1e8: usd_candidates.append({'entity':o['entity'],'token':o['token'],'underlying_raw_loss_1e18':(-o['delta_raw'])*v//10**18,'usd_loss_candidate_1e8':(-o['delta_raw'])*v*btc_price_1e8//10**36})
 for item in usd_candidates:
  raw=c('eth_call',[{'to':item['token'],'data':'0x07a2d13a'+format(next(-o['delta_raw'] for o in observations if o['entity']==item['entity'] and o['token']==item['token']),'064x')},hex(b-1)])
  item['convertToAssets_raw']=None if raw in (None,'0x','0x0') else int(raw,16)
 underlying_addresses={v['asset'] for v in valuation.values() if v.get('asset')}
 underlying_transfer_logs=[x for x in logs if x['token'] in underlying_addresses]
 out={'schema_version':1,'status':'RAW_RECEIPT_TOKEN_TRANSFER_ONLY_IMMEDIATE_REDEEMABILITY_VERIFIED_POLICY_PENDING','tx_hash':TX,'block':b,'tx_index':int(tx['transactionIndex'],16),'receipt_status':int(rec['status'],16),'attacker_eoa':tx['from'].lower(),'protected_entity_candidates':ENTITIES,'transfer_logs':logs,'underlying_transfer_logs':underlying_transfer_logs,'redeem_or_withdraw_underlying_observed':bool(underlying_transfer_logs),'immediate_redeemability':{'verified_source':True,'condition':'shares <= balanceOf(owner)','lock_or_cooldown_found':False,'redeem_effect':'burn shares and transfer underlying assets'},'balance_observations':observations,'underlying_balance_observations':underlying_balances,'wrapper_valuation_observations':valuation,'valuation_source_semantics':'Verified YieldBasis source defines totalAssets as total underlying asset managed; convertToAssets(shares) queried at target-1 is a mark-to-NAV conversion of receipt-token loss.','btc_usd_reference':{'feed':feed,'answer_1e8':btc_price_1e8,'timestamp':price_timestamp,'observed_at_block':b-1},'usd_loss_candidates':usd_candidates,'missing':['freeze receipt-token mark-to-NAV as the permitted transaction-scope harm measure and freeze aggregation policy','direct underlying balance delta is zero for queried strategy addresses'],'causal_authorized':False}
 p=ROOT/'eval/results/m6_giddy_historical_harm_observations.json'; p.write_text(json.dumps(out,indent=2)+'\n'); print('wrote',p,'logs',len(logs),'observations',len(observations))
if __name__=='__main__': main()
