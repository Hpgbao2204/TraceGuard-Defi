"""Rank unresolved positive rows for bounded A5 provenance recovery."""
from __future__ import annotations
import json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def main():
    src=ROOT/'eval/vnext/recovery/positive_tx_role_audit.jsonl'; rows=[]
    for line in src.read_text().splitlines():
        r=json.loads(line)
        if r.get('tx_role')!='REQUIRES_REVIEW': continue
        patterns=' '.join(r.get('source_evidence_patterns',[])).lower()
        multi='multi' in patterns or 'approval' in patterns or 'setup' in patterns
        if any(x in patterns for x in ('exploit tx','attack tx','drain tx','sweep tx')): tier='TIER_1_SOURCE_EXPLICIT_ROLE'
        elif multi: tier='TIER_3_MULTI_TX_ROLE_REVIEW'
        elif r.get('source_url'): tier='TIER_2_SOURCE_HASH_ROLE_UNCLEAR'
        else: tier='TIER_4_WEAK_OR_MISSING_PROVENANCE'
        r.update({'a5_tier':tier,'a5_priority':{'TIER_1_SOURCE_EXPLICIT_ROLE':1,'TIER_2_SOURCE_HASH_ROLE_UNCLEAR':2,'TIER_3_MULTI_TX_ROLE_REVIEW':3,'TIER_4_WEAK_OR_MISSING_PROVENANCE':4}[tier], 'a5_status':'PENDING_GIT_HISTORY_AND_P2_P3'})
        rows.append(r)
    rows.sort(key=lambda r:(r['a5_priority'],r['incident_id'],r['tx_hash']))
    d=ROOT/'eval/vnext/recovery'; p=d/'positive_a5_provenance_triage.jsonl'; p.write_text(''.join(json.dumps(r,sort_keys=True)+'\n' for r in rows))
    counts={t:sum(r['a5_tier']==t for r in rows) for t in sorted({r['a5_tier'] for r in rows})}
    s={'schema_version':1,'stage':'A5','input_records':len(rows),'tiers':counts,'next_action':'recover Tier 1 by full git-history search, then independent P2/P3; no auto-promotion'}
    (d/'positive_a5_provenance_triage_summary.json').write_text(json.dumps(s,indent=2,sort_keys=True)+'\n'); print(json.dumps(s,indent=2))
if __name__=='__main__': main()
