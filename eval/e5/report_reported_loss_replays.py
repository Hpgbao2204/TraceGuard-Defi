"""Summarize prior real replays for RCA cases with reported loss and T0 HARM."""
from __future__ import annotations
import json, hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'eval/results/e5_rcfh/reported_loss_replay_report.json'

def main() -> None:
    t0 = json.loads((ROOT / 'eval/results/m6_harm_detection_v2_fixed20_t0.json').read_text())
    t0 = {x['case_id']: x for x in t0['cases']}
    prior = [json.loads(line) for line in (ROOT / 'eval/results/m6_b2_results_r5.json').read_text().splitlines() if line.strip()]
    wanted = {'defihacklabs-silofinance-2025-06-25','defihacklabs-onyxdao-2024-09-26'}
    rows = []
    for record in prior:
        if record.get('case_id') not in wanted:
            continue
        base = next((r for r in record.get('rows', []) if r.get('mutation') == 'fidelity'), None)
        interventions = [r for r in record.get('rows', []) if r.get('mutation') != 'fidelity']
        rows.append({
            'case_id': record['case_id'],
            'reported_loss_case': True,
            'baseline_t0': {'status': t0.get(record['case_id'], {}).get('status'), 'hard_deltas': t0.get(record['case_id'], {}).get('hard_deltas', {})},
            'baseline_replay': {k: base.get(k) for k in ('outcome','fidelity_pass','harm_S','prestate_proof_verified')} if base else None,
            'interventions': [{k: r.get(k) for k in ('mutation','outcome','fidelity_pass','intervention_valid','harm_S','harm_Sm','verdict','override_applied','revert_reason')} for r in interventions],
            'e5_verdict': 'INCONCLUSIVE_HARM_NOT_MATERIALIZED',
            'reason': 'historical mutation replay exists, but mutated protocol HarmVector was not materialized; T0 baseline is screening evidence only',
        })
    result = {'schema_version':1,'artifact':'e5-reported-loss-replay-report','corpus_id':'m4-frozen-20','source_artifact':'eval/results/m6_b2_results_r5.json','source_sha256':hashlib.sha256((ROOT/'eval/results/m6_b2_results_r5.json').read_bytes()).hexdigest(),'cases':rows,'policy':'reported loss and T0 HARM do not substitute for paired protocol-scoped HarmVector','causal_verdicts':0}
    OUT.write_text(json.dumps(result, indent=2, sort_keys=True)+'\n')
    print(json.dumps({'cases':len(rows),'causal_verdicts':0,'statuses':[x['case_id'] for x in rows]},indent=2))

if __name__=='__main__': main()
