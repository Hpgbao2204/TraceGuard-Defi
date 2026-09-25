"""Rank hard-negative leads using observable similarity only.

This is candidate mining, not protocol matching and not benign labeling.
"""
import csv, json, hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
QUEUE=ROOT/'eval/results/hard_negative_review_queue.csv'
CACHE=ROOT/'eval/results/e1_trace_cache.jsonl'
OUT=ROOT/'eval/results/hard_negative_strict_mining_leads.json'
FIXED={x['case_id'] for x in json.load(open(ROOT/'docs/m4_frozen_case_manifest.json'))['cases']}
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def features(t):
    x=t.get('trace') or {}; calls=x.get('flat_calls') or []
    selectors={str(c.get('input',''))[:10].lower() for c in calls if str(c.get('input','')).startswith('0x')}
    types={str(c.get('type','')).upper() for c in calls}
    addresses={str(c.get(k)).lower() for c in calls for k in ('from','to') if c.get(k)}
    return selectors,types,addresses
def main():
    cache={}
    for line in CACHE.read_text().splitlines():
        if line.strip():
            r=json.loads(line); cache[str(r.get('tx_hash','')).lower()]=r
    leads=[]
    for row in csv.DictReader(QUEUE.open()):
        attack=cache.get(row['attack_tx_hash'].lower(),{}); cand=cache.get(row['candidate_tx_hash'].lower(),{})
        a_sel,a_types,a_addr=features(attack); c_sel,c_types,c_addr=features(cand)
        within=row['within_window'].lower()=='true'
        selector_overlap=len(a_sel&c_sel); type_overlap=len(a_types&c_types); addr_overlap=len(a_addr&c_addr)
        # Ranking only; no field below establishes protocol relation.
        score=(100 if within else 0)+min(selector_overlap,10)*5+min(type_overlap,4)*2+min(addr_overlap,4)
        leads.append({'attack_case_id':row['attack_case_id'],'attack_tx_hash':row['attack_tx_hash'],
                      'candidate_tx_hash':row['candidate_tx_hash'],'attack_block':int(row['attack_block']),
                      'candidate_block':int(row['candidate_block']),'block_distance':int(row['block_distance']),
                      'within_window':within,'observable_similarity':{'selector_overlap':selector_overlap,'call_type_overlap':type_overlap,'trace_address_overlap':addr_overlap},
                      'ranking_score':score,'protocol_relation':'unresolved','benign_status':'unreviewed','review_required':True})
    leads.sort(key=lambda x:(-x['ranking_score'],x['block_distance'],x['candidate_tx_hash']))
    result={'schema_version':1,'status':'REVIEW_LEADS_ONLY','selection_policy':'observable temporal/call-shape similarity; no protocol or benign labels inferred','source_queue_sha256':sha(QUEUE),'source_trace_cache_sha256':sha(CACHE),'candidate_count':len(leads),'within_window_count':sum(x['within_window'] for x in leads),'leads':leads}
    OUT.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n'); print(json.dumps({'candidate_count':len(leads),'within_window_count':result['within_window_count'],'out':str(OUT)},indent=2))
if __name__=='__main__': main()
