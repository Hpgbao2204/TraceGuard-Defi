"""Annotate transaction roles from explicit source wording; never promote labels."""
from __future__ import annotations
import json, re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
ROLE_PATTERNS=(('approval',r'approval\s+tx'),('setup',r'setup\s+tx'),('drain',r'drain\s+tx'),('sweep',r'sweep\s+tx'),('exploit',r'exploit\s+tx'),('exploit',r'attack\s+tx'),('exploit',r'incident\s+tx'),('exploit',r'claim\s+tx'))
def main():
    incidents={json.loads(x)['id']:json.loads(x) for x in (ROOT/'corpus/incidents.jsonl').read_text().splitlines() if x.strip()}
    resolutions=[json.loads(x) for x in (ROOT/'eval/vnext/recovery/positive_a1_resolution.jsonl').read_text().splitlines() if x.strip()]
    out=[]
    for res in resolutions:
        src=incidents[res['incident_id']]; text=(src.get('notes') or '').lower()
        for rr in res.get('results',[]):
            tx=rr['hash'].lower(); role=None; evidence=[]
            for candidate,pat in ROLE_PATTERNS:
                if tx in text and re.search(pat+r'.*?'+re.escape(tx),text,re.S): role=candidate; evidence.append(pat)
            canonical = role in {'exploit','drain','sweep'} if role else None
            out.append({'incident_id':res['incident_id'],'tx_hash':rr['hash'],'chain':res['chain'],'tx_role':role or 'REQUIRES_REVIEW','canonical_attack_tx':canonical,'source_url':src.get('source_url'),'source_evidence_patterns':evidence,'policy':'Role derived only when source explicitly binds role to this hash; final promotion requires P1/P2/P3 review.'})
    dest=ROOT/'eval/vnext/recovery'; dest.mkdir(parents=True,exist_ok=True)
    (dest/'positive_tx_role_audit.jsonl').write_text(''.join(json.dumps(x,sort_keys=True)+'\n' for x in out))
    lumi=[x for x in out if x['incident_id']=='defihacklabs-lumi-finance-2026-07-14']
    summary={'schema_version':1,'status':'ROLE_AUDIT_ONLY','records':len(out),'role_counts':{},'lumi':lumi}
    for x in out: summary['role_counts'][x['tx_role']]=summary['role_counts'].get(x['tx_role'],0)+1
    (dest/'positive_tx_role_audit_summary.json').write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n'); print(json.dumps({'records':len(out),'role_counts':summary['role_counts'],'lumi':lumi},indent=2))
if __name__=='__main__': main()
