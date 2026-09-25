"""Build four disjoint fidelity set files from acquired 80-case metadata."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
ACQ=ROOT/'eval/results/e5_rcfh/defihacklabs_replay_acquisition.json'
POOL=ROOT/'eval/results/e5_rcfh/defihacklabs_t0_candidate_pool.json'
OUT=ROOT/'eval/results/e5_rcfh/fidelity_parallel_sets'
def main():
    acq={x['candidate_id']:x for x in json.loads(ACQ.read_text())['cases']}
    pool={x['candidate_id']:x for x in json.loads(POOL.read_text())['candidates']}
    rows=[]
    for cid,a in acq.items():
        p=pool[cid]
        rows.append({'case_id':cid,'protocol':p['incident']['protocol'],'attack_type':p['reported_root_cause']['family'],'tx_hash':a['tx_hash'],'block':a['block'],'tx_index':a['tx_index'],'mainnet_gas':a['mainnet_gas'],'reason':'DeFiHackLabs 80-case expansion; selection frozen before replay'})
    rows.sort(key=lambda x:x['case_id'])
    OUT.mkdir(parents=True,exist_ok=True)
    for i in range(4):
        payload={'schema_version':1,'name':f'defihacklabs-80-parallel-{i}','selection_seed':'frozen-candidate-pool','cases':rows[i*20:(i+1)*20]}
        (OUT/f'set_{i}.json').write_text(json.dumps(payload,indent=2)+'\n')
    print({'sets':4,'cases':len(rows),'sizes':[20]*4})
if __name__=='__main__': main()
