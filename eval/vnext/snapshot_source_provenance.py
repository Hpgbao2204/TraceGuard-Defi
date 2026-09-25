"""Fetch immutable GitHub source snapshots for source-explicit A1 rows."""
from __future__ import annotations
import hashlib,json,os,re,urllib.request,urllib.parse
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def get(url):
    req=urllib.request.Request(url,headers={'User-Agent':'TraceGuard-vNext-provenance/1.0','Accept':'application/vnd.github+json'})
    with urllib.request.urlopen(req,timeout=15) as r:return r.read()
def main():
    rows=[json.loads(x) for x in (ROOT/'eval/vnext/recovery/positive_a2_explorer_crosscheck.jsonl').read_text().splitlines() if x.strip() and json.loads(x).get('p2_explorer_tx') and json.loads(x).get('p3_explorer_receipt')]
    # Keep only source-explicit rows; current batch has two explorer-confirmed rows.
    rows=[r for r in rows if r.get('source_explicitly_identifies_exploit_tx')]
    out=ROOT/'eval/vnext/recovery/source_snapshots'; out.mkdir(parents=True,exist_ok=True); records=[]
    for r in rows:
        m=re.match(r'https://github\.com/([^/]+)/([^/]+)/blob/[^/]+/(.+)',r.get('source_url',''))
        rec={'incident_id':r['incident_id'],'tx_hash':r['tx_hash'],'source_url':r.get('source_url'),'status':'UNRESOLVED'}
        if not m: rec['reason_code']='UNSUPPORTED_SOURCE_URL'; records.append(rec); continue
        owner,repo,path=m.groups(); api=f'https://api.github.com/repos/{owner}/{repo}/commits?path={urllib.parse.quote(path)}&per_page=1'
        try:
            commits=json.loads(get(api)); sha=commits[0]['sha'] if commits else None
            if not sha: raise ValueError('no commit found for source path')
            raw=get(f'https://raw.githubusercontent.com/{owner}/{repo}/{sha}/{path}')
            dest=out/(r['incident_id']+'__'+Path(path).name); dest.write_bytes(raw)
            contains=r['tx_hash'].lower().encode() in raw.lower()
            rec.update({'status':'SOURCE_SNAPSHOT_READY' if contains else 'SOURCE_SNAPSHOT_MISSING_HASH','commit_sha':sha,'snapshot_path':str(dest.relative_to(ROOT)),'snapshot_sha256':hashlib.sha256(raw).hexdigest(),'hash_explicit_in_snapshot':contains,'bytes':len(raw)})
        except Exception as e: rec['reason_code']=type(e).__name__+': '+str(e)
        records.append(rec)
    d=ROOT/'eval/vnext/recovery'; (d/'source_provenance_snapshots.jsonl').write_text(''.join(json.dumps(x,sort_keys=True)+'\n' for x in records))
    summary={'schema_version':1,'status':'SNAPSHOT_ONLY','records':len(records),'snapshot_ready':sum(x.get('status')=='SOURCE_SNAPSHOT_READY' for x in records),'snapshot_missing_hash':sum(x.get('status')=='SOURCE_SNAPSHOT_MISSING_HASH' for x in records),'promoted':0,'policy':'Immutable source snapshot is necessary but not sufficient; P1 incident-role review remains required.'}
    (d/'source_provenance_snapshots_summary.json').write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n'); print(json.dumps(summary,indent=2))
if __name__=='__main__': main()
