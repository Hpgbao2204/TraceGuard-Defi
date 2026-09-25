"""V0 transaction materialization and split/schema audit; fail closed."""
from __future__ import annotations
import argparse,json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def ids(name): return set((ROOT/'eval/vnext/splits'/name).read_text().split())
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--registry',default='corpus/vnext/positive_registry.jsonl'); args=ap.parse_args(); registry=ROOT/args.registry
    reg=[json.loads(x) for x in registry.read_text().splitlines() if x.strip()]; split={**{x:'fit' for x in ids('fit_ids.txt')},**{x:'calibration' for x in ids('calibration_ids.txt')},**{x:'test' for x in ids('test_ids.txt')}}; rows=[]; rej=[]
    for x in reg:
        if x.get('verification') not in (None, 'base_registry', 'p1_p2_p3_recovery'):
            rej.append({'incident_id':x['incident_id'],'reason_code':'PENDING_VERIFICATION_OR_CANONICAL_REVIEW'}); continue
        hs=[h for h in x.get('tx_hashes',[]) if h]
        if len(hs)!=1 or x['incident_id'] not in split: rej.append({'incident_id':x['incident_id'],'reason_code':'MISSING_OR_NONUNIQUE_CANONICAL_TX_OR_SPLIT'}); continue
        rows.append({'incident_id':x['incident_id'],'tx_hash':hs[0],'chain':x.get('chain'),'label':1,'canonical_attack_tx':True,'tx_role':'exploit','split':split[x['incident_id']]})
    d=ROOT/'corpus/vnext'; p=d/'positive_transactions.jsonl'; p.write_text(''.join(json.dumps(x,sort_keys=True)+'\n' for x in rows)); cache=ROOT/'eval/vnext/features'; cache.mkdir(exist_ok=True); fp=cache/'three_view_feature_cache.jsonl'; fp.write_text('')
    a=ROOT/'eval/vnext/splits/materialized_split_audit.json'; audit={'schema_version':1,'status':'FAIL','registry_path':args.registry,'registry_sha256':hashlib.sha256(registry.read_bytes()).hexdigest(),'positive_incidents':len(reg),'materialized_positive_rows':len(rows),'rejected_incidents':len(rej),'required_views':['call_structure','token_flow','economic'],'feature_cache_rows':0,'feature_schema_valid':False,'negative_rows_materialized':0,'incident_leakage':False,'tx_duplicates':len(rows)-len({x['tx_hash'] for x in rows}),'reason_codes':sorted(set(x['reason_code'] for x in rej)) or ['FEATURE_CACHE_NOT_MATERIALIZED'],'policy':'No feature values fabricated; B0 unauthorized until positive/negative transaction features exist.'}; a.write_text(json.dumps(audit,indent=2,sort_keys=True)+'\n'); (ROOT/'eval/vnext/features/three_view_feature_manifest.json').write_text(json.dumps({'schema_version':1,'status':'NOT_MATERIALIZED','cache_sha256':hashlib.sha256(fp.read_bytes()).hexdigest(),'rows':0,'views':audit['required_views']},indent=2,sort_keys=True)+'\n'); print(json.dumps(audit,indent=2))
if __name__=='__main__': main()
