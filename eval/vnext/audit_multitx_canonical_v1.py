"""Bounded, source-bound canonicalization audit for six multi-tx incidents."""
import hashlib,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
IDS={'defihacklabs-adsharesbridge-2026-05-15','defihacklabs-aztec-v1-2026-06-17','defihacklabs-bubai-2024-10-29','defihacklabs-hegicoptions-2025-02-23','defihacklabs-unilend-2025-01-12','defihacklabs-veth-2024-11-14'}
def main():
 reg=[json.loads(x) for x in (ROOT/'corpus/vnext/positive_registry.jsonl').read_text().splitlines() if x.strip() and json.loads(x).get('incident_id') in IDS]
 out=[]
 for x in sorted(reg,key=lambda z:z['incident_id']):
  path=next(iter((ROOT/'eval/vnext/recovery').glob(f'**/{x["incident_id"]}__*.sol')),None); text=path.read_text(errors='ignore') if path else ''
  txs=[]
  for h in x.get('tx_hashes',[]):
   near=' '.join(text[max(0,text.lower().find(h.lower())-180):text.lower().find(h.lower())+len(h)+180]) if h.lower() in text.lower() else ''
   role='unknown'
   for r in ('setup','approval','auxiliary','revert','exploit','attack','drain','sweep'):
    if re.search(r'\b'+r+r'\s+tx\b|\b'+r+r'\s+transaction\b',near,re.I): role=r; break
   txs.append({'tx_hash':h,'source_local_context':near,'source_role':role})
  candidates=[t for t in txs if t['source_role'] in ('exploit','attack','drain','sweep')]
  status='CANONICAL_CANDIDATE_UNIQUE' if len(candidates)==1 else 'UNRESOLVED_CANONICAL'
  out.append({'incident_id':x['incident_id'],'chain':x.get('chain'),'status':status,'candidates':candidates,'all_transactions':txs,'policy':'Source-bound roles only; setup/approval/revert excluded; no TSV/first-row authority.'})
 p=ROOT/'eval/vnext/gates/gate_v0_1_multitx_canonical_audit.json'; p.parent.mkdir(exist_ok=True,parents=True); p.write_text(json.dumps({'schema_version':1,'policy_version':'canonicalization-v1','source_registry_sha256':hashlib.sha256((ROOT/'corpus/vnext/positive_registry.jsonl').read_bytes()).hexdigest(),'records':out,'summary':{'unique_candidate':sum(x['status']=='CANONICAL_CANDIDATE_UNIQUE' for x in out),'unresolved':sum(x['status']=='UNRESOLVED_CANONICAL' for x in out)}},indent=2,sort_keys=True)+'\n'); print(json.dumps(json.loads(p.read_text()),indent=2))
if __name__=='__main__':main()
