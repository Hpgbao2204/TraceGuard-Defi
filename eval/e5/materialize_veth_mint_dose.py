#!/usr/bin/env python3
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = Path('/tmp/veth-mint-150.json')
OUT = ROOT / 'eval/results/e5_rcfh/veth_buyquote_dose_probe/mint_amount_150e18_replay.json'

def main():
    d = json.loads(RAW.read_text())
    t = d['per_tx'][57]
    out = {
        'status': 'INCONCLUSIVE_MINT_DOSE_REVERT',
        'case_id': 'defihacklabs-veth-2024-11-14',
        'dose': {'original_amount_raw': '3000000000000000000000', 'replacement_amount_raw': '150000000000000000000'},
        'intervention': t.get('call_intervention'),
        'replay_gates': {k: d.get(k) for k in ('acceptance_gate','all_status_match','all_gas_match','all_logs_match','relevant_post_state_match')},
        'target_result': {k: t.get(k) for k in ('expected_status','actual_status','status_match','gas_match','logs_match','post_state_match')},
        'revert_diagnosis': {
            'trace_index': 106,
            'depth': 3,
            'error': 'insufficient balance for transfer',
            'preceding_call': '0x351d...00c9 -> WETH.deposit() with 5426.700593482696725462 ETH',
            'classification': 'same_repayment_funding_failure_as_capital_dose',
        },
        'interpretation': 'The amount-only rewrite matched the exact mint call once and was applied, but the root transaction reverted at the final WETH deposit because the reduced mint produced too little reverse-settlement ETH to fund the fixed flash-loan repayment. This is a feasibility boundary diagnostic, not a profit dose-response or causal verdict.',
        'raw_sha256': hashlib.sha256(RAW.read_bytes()).hexdigest(),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2) + '\n')
    print(OUT)
    print(hashlib.sha256(OUT.read_bytes()).hexdigest())

if __name__ == '__main__': main()
