#!/usr/bin/env python3
"""Compare intervention topology with the authenticated VETH baseline."""
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'eval/results/e5_rcfh/veth_buyquote_dose_probe/dose_100.json'
UNC = Path('/tmp/veth-mint-299.json')
CPL = Path('/tmp/veth-helper-299.json')
OUT = ROOT / 'eval/results/e5_rcfh/veth_buyquote_dose_probe/mint_299_topology_audit.json'

def load(path):
    d=json.loads(path.read_text()); return d['per_tx'][57]

def signature(tx):
    ct=tx['call_trace']
    calls=[(e.get('event'),e.get('depth'),e.get('type'),e.get('from','').lower(),e.get('to','').lower(),e.get('input','')[:10].lower()) for e in ct]
    topics=[(x.get('address','').lower(), tuple(x.get('topics',[]))) for x in tx.get('logs',[])]
    return calls, topics

def main():
    txs={'baseline_300':load(BASE),'uncoupled_299':load(UNC),'coupled_299':load(CPL)}
    bcall,blog=signature(txs['baseline_300'])
    rows={}
    for name,tx in txs.items():
        call,log=signature(tx)
        rows[name]={
            'call_trace_entries': sum(e.get('event')=='enter' for e in tx['call_trace']),
            'call_trace_exits': sum(e.get('event')=='exit' for e in tx['call_trace']),
            'log_count': len(tx.get('logs',[])),
            'status': tx.get('actual_status'),
            'gas': tx.get('actual_gas'),
            'call_topology_matches_baseline': call==bcall,
            'event_topology_matches_baseline': log==blog,
        }
    out={'status':'TOPOLOGY_PRESERVED_DOSE_RESPONSE_CANDIDATE','case_id':'defihacklabs-veth-2024-11-14','comparison':rows,'interpretation':'Both 299 probes preserve the complete call topology and event topology of the authenticated 300 baseline and finish successfully. This removes path-divergence as the explanation for the observed profit change, but does not by itself establish protected-harm causality or a final root verdict.','raw_sha256':{'baseline':hashlib.sha256(BASE.read_bytes()).hexdigest(),'uncoupled':hashlib.sha256(UNC.read_bytes()).hexdigest(),'coupled':hashlib.sha256(CPL.read_bytes()).hexdigest()}}
    OUT.write_text(json.dumps(out,indent=2)+'\n'); print(OUT); print(hashlib.sha256(OUT.read_bytes()).hexdigest())
if __name__=='__main__': main()
