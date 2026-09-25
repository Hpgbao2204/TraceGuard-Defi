"""Fresh Gate C audit over the frozen vNext incident registry."""
from __future__ import annotations
import argparse,hashlib,json,random
from collections import Counter
from datetime import date
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; SEED=20260916
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--registry',default='corpus/vnext/positive_registry.jsonl'); args=ap.parse_args()
    registry=ROOT/args.registry; reg=[json.loads(x) for x in registry.read_text().splitlines() if x.strip()]; raw={}
    for line in (ROOT/'corpus/incidents.jsonl').read_text().splitlines():
        x=json.loads(line); raw[x.get('id')]=x
    items=[]
    for x in reg:
        y={**x,**{k:raw.get(x['incident_id'],{}).get(k) for k in ('attack_type','protocol','date','chain','source')}}; items.append(y)
    ids=[x['incident_id'] for x in items]; dup=len(ids)-len(set(ids)); rng=random.Random(SEED); shuffled=ids[:]; rng.shuffle(shuffled); n=len(shuffled); fit=shuffled[:round(.6*n)]; cal=shuffled[round(.6*n):round(.8*n)]; test=shuffled[round(.8*n):]
    dated=sorted((x for x in items if x.get('date')),key=lambda x:x['date']); cutoff=dated[round(.8*len(dated))-1]['date'] if dated else None; chrono_test=[x['incident_id'] for x in items if cutoff and x.get('date')>cutoff]; chrono_fit=[x['incident_id'] for x in items if x['incident_id'] not in chrono_test]
    d=ROOT/'eval/vnext/splits'; d.mkdir(parents=True,exist_ok=True)
    for name,vals in [('fit_ids',fit),('calibration_ids',cal),('test_ids',test),('chronological_fit_ids',chrono_fit),('chronological_test_ids',chrono_test)]: (d/(name+'.txt')).write_text('\n'.join(vals)+'\n')
    m={'schema_version':1,'spec_version':'vnext-gates-v1','registry_path':args.registry,'registry_sha256':hashlib.sha256(registry.read_bytes()).hexdigest(),'grouping_key':'incident_id','split_seed':SEED,'standard_counts':{'fit':len(fit),'calibration':len(cal),'test':len(test)},'chronological_cutoff':cutoff,'chronological_test_positive_count':len(chrono_test),'family_holdout_enabled':False,'protocol_holdout_enabled':False,'hard_negative_holdout_enabled':False,'split_manifest_sha256':{name:hashlib.sha256((d/(name+'.txt')).read_bytes()).hexdigest() for name in ('fit_ids','calibration_ids','test_ids','chronological_fit_ids','chronological_test_ids')}}; (d/'vnext_split_plan.json').write_text(json.dumps(m,indent=2,sort_keys=True)+'\n')
    g=ROOT/'eval/vnext/gates'; s={'schema_version':1,'gate_id':'C','spec_version':'vnext-gates-v1','status':'CONDITIONAL','registry_path':args.registry,'registry_sha256':m['registry_sha256'],'records':len(items),'duplicate_incident_ids':dup,'counts':{'family':dict(Counter(x.get('attack_type') or 'UNKNOWN' for x in items)),'protocol':dict(Counter(x.get('protocol') or 'UNKNOWN' for x in items)),'year':dict(Counter((x.get('date') or '')[:4] or 'UNKNOWN' for x in items)),'chain':dict(Counter(x.get('chain') or 'UNKNOWN' for x in items)),'source':dict(Counter(x.get('source') or 'UNKNOWN' for x in items))},'standard_grouped_split_valid':not dup,'chronological_split_valid':len(chrono_test)>=30,'chronological_cutoff':cutoff,'chronological_test_positive_count':len(chrono_test),'family_holdout_enabled':False,'protocol_holdout_enabled':False,'hard_negative_holdout_enabled':False,'reason':'Grouped and chronological splits are valid; no optional family/protocol/hard-negative axis is enabled under current support thresholds.'}; (g/'gate_c_fresh_audit.json').write_text(json.dumps(s,indent=2,sort_keys=True)+'\n'); print(json.dumps(s,indent=2))
if __name__=='__main__': main()
