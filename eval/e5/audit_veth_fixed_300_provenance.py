#!/usr/bin/env python3
import json
from decimal import Decimal
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
CASE=ROOT/'eval/results/m4/b2-contexts-fresh/defihacklabs-veth-2024-11-14'
OUT=ROOT/'eval/results/e5_rcfh/veth_buyquote_dose_probe/fixed_300_token0_provenance.json'
PAIR='0x582d17d24127cfdcbc8c4e0a40c12d77b2e7a48d'
TOKEN='0x280a8955a11fcd81d72ba1f99d265a48ce39ac2e'
HELPER='0x62f250cf7021e1cf76c765dec8ec623fe173a1b5'

def main():
 t=json.loads((CASE/'b2-replay-m4.json').read_text())['per_tx'][57]['call_trace']
 e45=t[45]; e48=t[48]
 amount=int(e48['input'][-64:],16)
 out={'status':'DIAGNOSTIC_FIXED_LEG_PROVENANCE','case_id':'defihacklabs-veth-2024-11-14','fixed_leg':{'amount_raw':str(amount),'amount_token0':str(Decimal(amount)/Decimal(10**18)),'mint_destination':PAIR,'mint_source':'0x0000000000000000000000000000000000000000'},'provenance':{'trace_45':{k:e45.get(k) for k in ('depth','type','from','to','input','value')},'trace_48':{k:e48.get(k) for k in ('depth','type','from','to','input','value')},'position':'after primary buyQuote/swap and before reverse settlement trace 77'},'interpretation':{'confirmed':'The fixed 300 token0 is minted from zero to the pair by a separate contract call, between the two swap phases; it is not the attacker cashIn amount and not a Factory direct transfer.','causal_status':'This leg is a candidate sequencing/liquidity-injection mechanism, not yet a root-cause verdict. Its intended protocol role and effect on attacker return still require a paired intervention.', 'next':'Compare the reverse settlement with and without this exact mint leg while preserving all other historical state; do not remove it by changing attacker capital.'}}
 OUT.parent.mkdir(parents=True,exist_ok=True); OUT.write_text(json.dumps(out,indent=2)+'\n'); print(OUT)
if __name__=='__main__': main()
