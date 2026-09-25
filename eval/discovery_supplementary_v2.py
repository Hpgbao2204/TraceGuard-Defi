"""Strict offline discovery gate for new supplementary leads."""
import json, hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
INC=ROOT/'corpus/incidents.jsonl'; FIX=ROOT/'docs/m4_frozen_case_manifest.json'; OLD=ROOT/'eval/results/m6_supplementary_candidate_leads.json'; OUT=ROOT/'eval/results/m6_supplementary_discovery_v2.json'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    fixed={x['case_id'] for x in json.loads(FIX.read_text())['cases']}; old={x['case_id'] for x in json.loads(OLD.read_text())['leads']}; leads=[]
    for r in (json.loads(x) for x in INC.read_text().splitlines() if x.strip()):
        if r['id'] in fixed|old or r.get('chain')!='ethereum' or r.get('verified')!='onchain' or not r.get('tx_hashes'): continue
        text=(r.get('notes') or '').lower()
        causal_flash=any(x in text for x in ('flash loan was necessary','flash-loan was necessary','flash loan is necessary','without the flash loan'))
        external_feed=any(x in text for x in ('chainlink feed','external price feed','external oracle feed','latestrounddata'))
        if causal_flash or external_feed: leads.append({'case_id':r['id'],'tx_hash':r['tx_hashes'][0],'preliminary_subtype':'f_fl_causal' if causal_flash else 'f_orc_external','evidence_source':r.get('source_url')})
    out={'schema_version':1,'status':'NO_NEW_STRICT_LEADS' if not leads else 'LEADS_REQUIRE_REVIEW','selection_rule':'known on-chain Ethereum incident plus explicit causal-flash or external-feed language; no replay outcome used','source_incidents_sha256':sha(INC),'lead_count':len(leads),'leads':leads}
    OUT.write_text(json.dumps(out,indent=2,sort_keys=True)+'\n'); print(json.dumps({'lead_count':len(leads),'status':out['status'],'out':str(OUT)},indent=2))
if __name__=='__main__': main()
