#!/usr/bin/env python3
import hashlib, json
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'eval/results/e5_rcfh/veth_buyquote_dose_probe/helper_coupled_floor_search.json'
DOSES = ['290','292','293','294','294.5','294.5625','294.59375','294.609375','294.625','294.75','294.875','295']

def main():
    rows = []
    for s in DOSES:
        raw = Path('/tmp/veth-helper-' + s + '.json')
        d = json.loads(raw.read_text())
        t = d['per_tx'][57]
        ok = bool(t.get('actual_status'))
        row = {'dose_token0': s, 'actual_status': t.get('actual_status'), 'actual_gas': t.get('actual_gas'), 'gas_match': t.get('gas_match'), 'status_match': t.get('status_match'), 'logs_match': t.get('logs_match'), 'acceptance_gate': d.get('acceptance_gate'), 'raw_sha256': hashlib.sha256(raw.read_bytes()).hexdigest()}
        if ok:
            cashout = Decimal(t['call_trace'][99]['value']) / Decimal(10**18)
            row.update({'cashout_eth': str(cashout), 'profit_eth': str(cashout - Decimal('5426.700593482696725462')), 'topology_entries': sum(e.get('event') == 'enter' for e in t['call_trace']), 'log_count': len(t.get('logs', []))})
        else:
            row['classification'] = 'FEASIBILITY_BOUNDARY_REVERT_NOT_A_PROFIT_OBSERVATION'
        rows.append(row)
    out = {'status': 'COUPLED_VIRTUAL_LIQUIDITY_FEASIBILITY_FLOOR_BRACKETED', 'case_id': 'defihacklabs-veth-2024-11-14', 'executing_interval': '[294.59375, 295]', 'reverting_interval': '[290, 294.5625]', 'points': rows, 'interpretation': 'The coupled helper dose remains executable at 294.59375e18, while 294.5625e18 reverts. The feasibility floor is bracketed in that interval. Profit values are reported only for successful runs and remain diagnostic, not a causal verdict.', 'raw_sha256s': {s: hashlib.sha256(Path('/tmp/veth-helper-' + s + '.json').read_bytes()).hexdigest() for s in DOSES}}
    OUT.write_text(json.dumps(out, indent=2) + '\n')
    print(OUT)
    print(hashlib.sha256(OUT.read_bytes()).hexdigest())

if __name__ == '__main__':
    main()
