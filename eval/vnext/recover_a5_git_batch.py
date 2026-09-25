"""Bounded A5 Git-history recovery; never promotes and never overwrites A3."""
from __future__ import annotations
import hashlib,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; CLONE=Path('/private/tmp/defihacklabs-history'); OFFSET=110; LIMIT=30
def git(*a): return subprocess.check_output(['git','-C',str(CLONE),*a],text=True).strip()
def main():
    tri=ROOT/'eval/vnext/recovery/positive_a5_provenance_triage.jsonl'
    rows=[json.loads(x) for x in tri.read_text().splitlines() if x.strip()][OFFSET:OFFSET+LIMIT]; out=[]
    d=ROOT/'eval/vnext/recovery/source_snapshots_a5_batch_004'; d.mkdir(exist_ok=True)
    for r in rows:
        tx=r['tx_hash']; rec={k:r[k] for k in ('incident_id','tx_hash','chain','source_url')}; rec['status']='UNRESOLVED'
        current=subprocess.run(['rg','-l',tx,str(CLONE/'src')],capture_output=True,text=True).stdout.splitlines()
        commits=git('log','--all','--full-history','--reverse','-S'+tx,'--format=%H','--','src').splitlines() if not current else ['WORKTREE']
        if not commits: rec['reason_code']='HASH_NOT_FOUND_IN_GIT_HISTORY'; out.append(rec); continue
        commit=commits[0]; paths=current if commit=='WORKTREE' else git('grep','-l',tx,commit,'--','src').splitlines()
        if not paths: rec['reason_code']='COMMIT_FOUND_BUT_PATH_NOT_FOUND'; out.append(rec); continue
        path=paths[0].split(':',1)[-1]; data=Path(path).read_bytes() if commit=='WORKTREE' else subprocess.check_output(['git','-C',str(CLONE),'show',f'{commit}:{path}'])
        if commit=='WORKTREE': path=str(Path(path).relative_to(CLONE))
        target=d/(r['incident_id']+'__'+Path(path).name); target.write_bytes(data)
        text=data.decode(errors='ignore'); rec.update({'status':'SOURCE_SNAPSHOT_READY','commit_sha':commit,'path':path,'snapshot_path':str(target.relative_to(ROOT)),'snapshot_sha256':hashlib.sha256(data).hexdigest(),'hash_explicit_in_snapshot':tx.lower() in text.lower(),'role_markers':[m for m in ('Exploit tx','Attack tx','Drain tx','Sweep tx','Setup tx','Approval tx') if m.lower() in text.lower()]})
        out.append(rec)
    dest=ROOT/'eval/vnext/recovery'; batch_path=dest/'positive_a5_git_batch_004.jsonl'; batch_path.write_text(''.join(json.dumps(x,sort_keys=True)+'\n' for x in out))
    (dest/'positive_a5_git_batch_004_manifest.json').write_text(json.dumps({'schema_version':1,'batch_id':'004','offset':OFFSET,'limit':LIMIT,'record_count':len(out),'tx_hashes':sorted(x['tx_hash'] for x in out),'batch_sha256':hashlib.sha256(batch_path.read_bytes()).hexdigest()},indent=2,sort_keys=True)+'\n')
    summary={'schema_version':1,'stage':'A5','batch_size':len(out),'source_snapshot_ready':sum(x.get('status')=='SOURCE_SNAPSHOT_READY' for x in out),'explicit_role':sum(bool(x.get('role_markers')) for x in out),'hash_not_found':sum(x.get('reason_code')=='HASH_NOT_FOUND_IN_GIT_HISTORY' for x in out),'status':'SNAPSHOT_ONLY_NO_PROMOTION'}
    (dest/'positive_a5_git_batch_004_summary.json').write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n'); print(json.dumps(summary,indent=2))
if __name__=='__main__': main()
