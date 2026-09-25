"""Recover source provenance from a local full Git clone by transaction hash."""
from __future__ import annotations
import hashlib,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
CLONE=Path('/private/tmp/defihacklabs-history')
def run(*args): return subprocess.check_output(['git','-C',str(CLONE),*args],text=True).strip()
def main():
    if not (CLONE/'.git').exists(): raise SystemExit('missing local DeFiHackLabs clone')
    rows=[json.loads(x) for x in (ROOT/'eval/vnext/recovery/positive_tx_role_audit.jsonl').read_text().splitlines() if x.strip()]
    rows=[r for r in rows if r.get('tx_role')=='exploit']
    dest=ROOT/'eval/vnext/recovery/source_snapshots_history'; dest.mkdir(parents=True,exist_ok=True); out=[]
    for r in rows:
        tx=r['tx_hash']; commits=run('log','--all','--full-history','--reverse','-S'+tx,'--format=%H','--','src').splitlines()
        rec={'incident_id':r['incident_id'],'tx_hash':tx,'chain':r.get('chain'),'status':'UNRESOLVED','source_url':r.get('source_url')}
        if not commits: rec['reason_code']='HASH_NOT_FOUND_IN_GIT_HISTORY'; out.append(rec); continue
        commit=commits[0]; paths=run('grep','-l',tx,commit,'--','src').splitlines()
        if not paths: rec['reason_code']='COMMIT_FOUND_BUT_PATH_NOT_FOUND'; out.append(rec); continue
        path=paths[0].split(':',1)[-1]; data=subprocess.check_output(['git','-C',str(CLONE),'show',f'{commit}:{path}'])
        target=dest/(r['incident_id']+'__'+Path(path).name); target.write_bytes(data)
        rec.update({'status':'SOURCE_SNAPSHOT_READY','commit_sha':commit,'path':path,'snapshot_path':str(target.relative_to(ROOT)),'snapshot_sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),'hash_explicit_in_snapshot':tx.lower().encode() in data.lower()})
        out.append(rec)
    d=ROOT/'eval/vnext/recovery'; (d/'source_provenance_git_history.jsonl').write_text(''.join(json.dumps(x,sort_keys=True)+'\n' for x in out))
    summary={'schema_version':1,'status':'SNAPSHOT_ONLY','records':len(out),'snapshot_ready':sum(x.get('status')=='SOURCE_SNAPSHOT_READY' for x in out),'hash_not_found':sum(x.get('reason_code')=='HASH_NOT_FOUND_IN_GIT_HISTORY' for x in out),'promoted':0,'policy':'Git snapshot supports P1 provenance review; it does not auto-promote VERIFIED_ATTACK.'}
    (d/'source_provenance_git_history_summary.json').write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n'); print(json.dumps(summary,indent=2))
if __name__=='__main__': main()
