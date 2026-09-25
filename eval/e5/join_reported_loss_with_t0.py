"""Join external reported-loss labels with existing factual T0 observations."""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'eval/results/e5_rcfh/reported_loss_priority.json'

def main() -> None:
    rca = json.loads((ROOT / 'eval/results/e5_rcfh/rca_dataset_reported_loss.json').read_text())
    t0doc = json.loads((ROOT / 'eval/results/m6_harm_detection_v2_fixed20_t0.json').read_text())
    t0 = {x['case_id']: x for x in t0doc.get('cases', [])}
    rows = []
    for item in rca['matches']:
        if item['reported_loss'] is None:
            continue
        factual = t0.get(item['case_id'], {})
        rows.append({
            'case_id': item['case_id'],
            'reported_loss': item['reported_loss'],
            'reported_root_cause': item['reported_root_cause'],
            'match_confidence': item['match_confidence'],
            't0_status': factual.get('status', 'MISSING'),
            't0_hard_deltas': factual.get('hard_deltas', {}),
            'replay_priority': 'HIGH' if factual.get('status') == 'HARM' else 'DIAGNOSTIC_ONLY',
            'measured_harm_semantics': 'T0 raw delta, not protocol-scoped proof-bound harm',
            'causal_replay': 'NOT_RUN',
        })
    result = {
        'schema_version': 1,
        'artifact': 'e5-reported-loss-priority',
        'corpus_id': 'm4-frozen-20',
        'rows': rows,
        'policy': 'reported loss prioritizes review; it does not establish measured harm or causal necessity',
        'high_priority_cases': [x['case_id'] for x in rows if x['replay_priority'] == 'HIGH'],
    }
    OUT.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'rows': len(rows), 'high_priority_cases': result['high_priority_cases']}, indent=2))

if __name__ == '__main__': main()
