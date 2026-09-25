"""Deterministic selection of a fidelity-passing B2 run."""
from __future__ import annotations
import hashlib, json
from pathlib import Path

class NoFidelityPassingRun(RuntimeError): pass

def _sha(x): return hashlib.sha256(json.dumps(x, sort_keys=True, separators=(',',':')).encode()).hexdigest()

def select_canonical_run(context_dir, tx_hash):
    candidates=[]
    for p in Path(context_dir).glob('b2-run-*.json'):
        d=json.loads(p.read_text())
        for row in d.get('per_tx',[]):
            if str(row.get('tx_hash','')).lower()!=tx_hash.lower(): continue
            accepted=all(row.get(k) is True for k in ('gas_match','status_match','logs_match')) and d.get('isolated_baseline_gate') is True
            if accepted:
                candidates.append((bool(row.get('post_state_match')),len(row.get('logs') or []),p.name,row,p))
    if not candidates: raise NoFidelityPassingRun(f'no passing run for {tx_hash}')
    # All passing runs must have identical committed payloads.
    payloads={_sha((x[3].get('logs'), x[3].get('call_trace'))) for x in candidates}
    if len(payloads)!=1: raise RuntimeError('NONDETERMINISTIC_B2')
    chosen=max(candidates, key=lambda x:(x[0],x[1],-ord(x[2][0]) if x[2] else 0, x[2]))
    row=chosen[3]
    row=dict(row); row['_run_name']=chosen[2]; row['_content_sha256']=hashlib.sha256(chosen[4].read_bytes()).hexdigest()
    return row
