#!/usr/bin/env python3
import json, hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
RAW=Path('/tmp/veth-block-fixed-leg.json')
OUT=ROOT/'eval/results/e5_rcfh/veth_buyquote_dose_probe/fixed_leg_block_replay.json'
def main():
 d=json.loads(RAW.read_text()); t=d['per_tx'][57]
 out={'status':'INCONCLUSIVE_BLOCKING_HELPER_CALL','case_id':'defihacklabs-veth-2024-11-14','intervention':t.get('call_intervention'),'replay_gates':{k:d.get(k) for k in ('acceptance_gate','all_status_match','all_gas_match','all_logs_match','relevant_post_state_match')},'target_result':{k:t.get(k) for k in ('expected_status','actual_status','status_match','gas_match','logs_match','post_state_match')},'interpretation':'Blocking the exact trace-45 helper CALL matched once and reverted the root transaction before reverse settlement. This proves the helper call is necessary for this execution path, but does not isolate whether the cause is the helper itself, its 300-token mint, its sequencing, or another side effect. A value-preserving/no-op or mint-only intervention is still required.','raw_sha256':hashlib.sha256(RAW.read_bytes()).hexdigest()}
 OUT.parent.mkdir(parents=True,exist_ok=True); OUT.write_text(json.dumps(out,indent=2)+'\n'); print(OUT); print(hashlib.sha256(OUT.read_bytes()).hexdigest())
if __name__=='__main__': main()
