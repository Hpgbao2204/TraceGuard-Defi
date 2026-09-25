"""Check proposed tx hashes against local incident/recovery evidence."""
import json
from pathlib import Path

ROOT=Path(__file__).parents[1]
HASHES={
"Dough Finance":"0x92cdcc732eebf47200ea56123716e337f6ef7d5ad714a2295794fdc6031ebb2e","Clober DEX":"0x8fcdfcded45100437ff94801090355f2f689941dca75de9a702e01670f361c04","XPEPE":"0xbdec39a74e620fc624f90483aff067b17044f81138e6c30038daf7f873159db4","UtopiaSphere":"0x1ddf415a4b18d25e87459ad1416077fe7398d5504171d4ca36e757b1a889f604","Palmswap":"0x62dba55054fa628845fecded658ff5b1ec1c5823f1a5e0118601aa455a30eac9","Radiant Capital":"0x1ce7e9a9e3b6dd3293c9067221ac3260858ce119ecb7ca860eac28b2474c7c9b","Sonne Finance":"0x45c0ccfd3ca1b4a937feebcb0f5a166c409c9e403070808835d41da40732db96","Onyx Protocol":"0xf7c21600452939a81b599017ee24ee0dfd92aaaccd0a55d02819a7658a6ef635","Euler Finance":"0xc310a0affe2169d1f6feec1c63dbc7f7c62a887fa48795d327d4d2da2d6b111d","Indexed Finance":"0x44aad3b853866468161735496a5d9cc961ce5aa872924c5d78673076b1cd95aa","Paribus":"0x0e29dcf4e9b211a811caf00fc8294024867bffe4ab2819cc1625d2e9d62390af","Bao Finance":"0xdd7dd68cd879d07cfc2cb74606baa2a5bf18df0e3bda9f6b43f904f4f7bbdfc1","FEG Token":"0x77cf448ceaf8f66e06d1537ef83218725670d3a509583ea0d161533fda56c063","OSN":"0xc7927a68464ebab1c0b1af58a5466da88f09ba9b30e6c255b46b1bc2e7d1bf09","TLN/VOW/VUSD":"0x1350cc72865420ba5d3c27234fd4665ad25c021b0a75ba03bc8340a1b1f98a45","TCH":"0xa94338d8aa312ed4b97b2a4dcb27f632b1ade6f3abec667e3bf9f002a75dabe0","Harvest Finance":"0x35f8d2f572fceaac9288e5d462117850ef2694786992a8c3f6d02612277b0877","PancakeBunny":"0x897c2de73dd55d7701e1b69ffb3a17b0f4801ced88b0c75fe1551c5fcce6a979","KyberSwap Elastic":"0x396a83df7361519416a6dc960d394e689dd0f158095cbc6a6c387640716f5475","Platypus Finance":"0x1266a937c2ccd970e5d7929021eed3ec593a95c68a99b4920c2efa226679b430"}
def main():
 found={}
 for path in [ROOT/'corpus/incidents.jsonl',ROOT/'corpus/verified_attacks.tsv']:
  if not path.exists(): continue
  for line in path.read_text(errors='ignore').splitlines():
   for h in HASHES.values():
    if h.lower() in line.lower(): found.setdefault(h.lower(),[]).append(str(path.relative_to(ROOT)))
 rows=[]
 for name,h in HASHES.items(): rows.append({'name':name,'tx_hash':h,'status':'LOCAL_HASH_MATCH' if h.lower() in found else 'NO_LOCAL_HASH_MATCH','evidence_files':found.get(h.lower(),[])})
 p=ROOT/'eval/results/m6_flashloan_candidate_integrity.json';p.write_text(json.dumps({'schema_version':1,'status':'IDENTITY_GATE_ONLY','cases':rows},indent=2)+'\n');print(json.dumps([(x['name'],x['status']) for x in rows],indent=2))
if __name__=='__main__':main()
