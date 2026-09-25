"""Baseline-only Harm-v2 audit for all frozen-20 factual B2 executions."""
import json
from pathlib import Path
from collections import Counter
ROOT=Path(__file__).resolve().parents[1]
def main():
    matrix={x['name']:x for x in json.loads((ROOT/'eval/results/m6_flashloan_20_status_matrix.json').read_text())['cases']}
    flow={x['case']:x for x in json.loads((ROOT/'eval/results/m6_flashloan_harm_flow_batch.json').read_text())['cases']}
    t0={x['case_id']:x for x in json.loads((ROOT/'eval/results/m6_harm_v2_t0_baseline.json').read_text())['cases']}
    rows=[]
    for case,m in matrix.items():
        f=flow.get(case,{})
        if m.get('b2')!='PASS':
            bucket, reason = 1, 'baseline fidelity failed or unverified'
        elif f.get('status') != 'FLOW_EXTRACTED':
            bucket, reason = 5, 'raw quantity unavailable (5A)'
        elif t0.get(case, {}).get('observation', {}).get('status') == 'UNKNOWN':
            # T0 has no valid attacker seed/complete observation.  An
            # explicit T1 boundary would be a separate recovery path, but
            # it cannot be inferred from this artifact.
            bucket, reason = 4, 'protected boundary/attacker seed unavailable for T0'
        else:
            # USD is deliberately not required by the raw predicate.  This is
            # 5B only when the factual artifact has raw flow + boundary; any
            # missing price is a reporting limitation, not UNKNOWN detection.
            bucket, reason = 5, 'raw quantity available; valuation optional (5B)'
        rows.append({
            'case_id': case,
            'baseline_fidelity': 'PASS' if m.get('b2') == 'PASS' else 'FAIL',
            'raw_flow_status': f.get('status'),
            't0_detection_status': t0.get(case, {}).get('observation', {}).get('status'),
            't0_detection_reason': t0.get(case, {}).get('observation', {}).get('reason_code'),
            'protected_boundary': f.get('protected_entity') if f.get('protected_entity') not in (None, 'PENDING_ADJUDICATION', '') else ('T0:auto-complement-v1' if t0.get(case, {}).get('observation', {}).get('status') in ('HARM', 'NO_HARM') else None),
            'primary_blocker': bucket,
            'primary_blocker_label': {
                1: 'BASELINE_FIDELITY_FAIL',
                2: 'NO_INTERVENTION_SEAM',
                3: 'COUNTERFACTUAL_BREAKS_BEFORE_HARM',
                4: 'PROTECTED_BOUNDARY_UNKNOWN',
                5: 'RAW_HARM_OBSERVATION_OR_VALUATION',
                6: 'MULTI_TX_OR_NON_ATOMIC',
            }[bucket],
            'reason': reason,
            'bucket_5_subtype': '5A' if bucket == 5 and f.get('status') != 'FLOW_EXTRACTED' else ('5B' if bucket == 5 else None),
            'blocks_causal_verdict': not (bucket == 5 and f.get('status') == 'FLOW_EXTRACTED'),
            'valuation_required_for_detection': False,
            'causal_replay_executed': False,
            'counterfactual_status': 'NOT_RUN',
            'taxonomy_verdict': 'NOT_EVALUABLE',
        })
    counts = {str(i): 0 for i in range(1, 7)}
    counts.update({str(k): v for k, v in Counter(str(x['primary_blocker']) for x in rows).items()})
    out={'schema_version':3,'detection_spec_id':'harm-spec-v2|T0/T1|hard-assets-v1','scope':'frozen-20 baseline-only audit','causal_replay_executed':False,'taxonomy':{'1':'baseline fidelity fail','2':'no intervention seam','3':'counterfactual execution breaks before harm observation','4':'protected boundary unknown','5':'raw harm observation unavailable / valuation unavailable','5A':'raw quantity unavailable','5B':'raw quantity available; USD unavailable/optional','6':'multi-tx / non-atomic'},'cases':rows,'counts':counts,'unobserved_blockers':{'2':'no factual seam adjudication in this baseline-only pass','3':'no counterfactual execution was run','6':'no atomicity adjudication field is present in frozen input'}}
    p=ROOT/'eval/results/m6_harm_v2_baseline_audit.json'; p.write_text(json.dumps(out,indent=2,sort_keys=True)+'\n'); print(json.dumps(out['counts'],indent=2))
if __name__=='__main__': main()
