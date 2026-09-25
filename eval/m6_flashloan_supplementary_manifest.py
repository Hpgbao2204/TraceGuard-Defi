"""Materialize a separate seven-case manifest for supplementary E4 work."""
import json, hashlib
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
CASES = [
 ('dough-finance-20288623','Dough Finance','0x92cdcc732eebf47200ea56123716e337f6ef7d5ad714a2295794fdc6031ebb2e',20288623,3),
 ('xpepe-21699659','XPEPE','0xbdec39a74e620fc624f90483aff067b17044f81138e6c30038daf7f873159db4',21699659,73),
 ('euler-finance-16817996','Euler Finance','0xc310a0affe2169d1f6feec1c63dbc7f7c62a887fa48795d327d4d2da2d6b111d',16817996,0),
 ('indexed-finance-13417949','Indexed Finance','0x44aad3b853866468161735496a5d9cc961ce5aa872924c5d78673076b1cd95aa',13417949,61),
 ('harvest-finance-11129474','Harvest Finance','0x35f8d2f572fceaac9288e5d462117850ef2694786992a8c3f6d02612277b0877',11129474,0),
 ('kyberswap-elastic-18630409','KyberSwap Elastic','0x396a83df7361519416a6dc960d394e689dd0f158095cbc6a6c387640716f5475',18630409,16),
 ('bao-finance-17620871','Bao Finance','0xdd7dd68cd879d07cfc2cb74606baa2a5bf18df0e3bda9f6b43f904f4f7bbdfc1',17620871,4),
]
def main():
 rows=[]
 for cid,name,tx,block,idx in CASES:
  rows.append({'case_id':cid,'protocol':name,'attack_type':'flash-loan exploit','tx_hash':tx,'block':block,'tx_index':idx,'chain':'ethereum','b2_acceptance':True,'harm_status':'PENDING_PROTECTED_ENTITY_ADJUDICATION','e4_status':'NOT_AUTHORIZED','notes':'Supplementary only; excluded from fixed-20.'})
 out=ROOT/'eval/results/m6_flashloan_supplementary_manifest.json'
 out.write_text(json.dumps({'schema_version':1,'scope':'supplementary seven B2-accepted candidates','fixed_20_unchanged':True,'causal_replay_authorized':False,'cases':rows},indent=2)+'\n')
 print(json.dumps({'case_count':len(rows),'sha256':hashlib.sha256(out.read_bytes()).hexdigest()}))
if __name__=='__main__': main()
