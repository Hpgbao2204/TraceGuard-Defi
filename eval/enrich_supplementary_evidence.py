"""Materialize safe, objective trace evidence for supplementary review."""
import hashlib, json
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
LEADS=ROOT/'eval/results/m6_supplementary_candidate_leads.json'
CACHE=ROOT/'eval/results/e1_trace_cache.jsonl'
OUT=ROOT/'eval/results/m6_supplementary_display_evidence.json'
def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def walk(c, out):
    if not isinstance(c,dict): return
    data=str(c.get('input') or '')
    out.append({'from':c.get('from'),'to':c.get('to'),'selector':data[:10] if data.startswith('0x') else None,'value':c.get('value'),'type':c.get('type'),'gas_used':c.get('gasUsed')})
    for child in c.get('calls') or []: walk(child,out)
def main():
    leads=json.loads(LEADS.read_text())['leads']; traces={}
    for line in CACHE.read_text().splitlines():
        if line.strip():
            r=json.loads(line); traces[str(r.get('tx_hash','')).lower()]=r.get('trace') or {}
    cases=[]
    for lead in leads:
        t=traces.get(lead['tx_hash'].lower(),{}); tree=t.get('tree') or {}; calls=[]; walk(tree,calls)
        addresses=sorted({x['to'].lower() for x in calls if x.get('to')})
        counts={}
        for call in calls: counts[call.get('type') or 'unknown']=counts.get(call.get('type') or 'unknown',0)+1
        selectors={}
        for call in calls:
            selector=call.get('selector') or 'none'; selectors[selector]=selectors.get(selector,0)+1
        cases.append({'case_id':lead['case_id'],'tx_hash':lead['tx_hash'].lower(),'source':{'artifact':'eval/results/e1_trace_cache.jsonl','field':'trace.tree'},'transaction':{'from':t.get('from'),'to':t.get('to'),'value':t.get('value')},'objective_summary':{'call_count':len(calls),'unique_contract_count':len(addresses),'call_type_counts':counts,'top_selectors':dict(sorted(selectors.items(),key=lambda x:(-x[1],x[0]))[:12])},'observed_calls':calls,'observed_contracts':addresses,'call_count':len(calls),'evidence_available':bool(t)})
    result={'schema_version':1,'source_leads_sha256':digest(LEADS),'source_trace_cache_sha256':digest(CACHE),'cases':cases}
    OUT.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n'); print(json.dumps({'cases':len(cases),'with_trace':sum(x['evidence_available'] for x in cases),'sha256':digest(OUT)},indent=2))
if __name__=='__main__': main()
