#!/usr/bin/env python3
"""Materialize the coupled virtual-liquidity dose diagnostic."""
import hashlib
import json
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = Path('/tmp/veth-helper-299.json')
OUT = ROOT / 'eval/results/e5_rcfh/veth_buyquote_dose_probe/helper_amount_299e18_coupled.json'

def word(data: str, index: int) -> int:
    return int(data[10 + index * 64:10 + (index + 1) * 64], 16)

def main() -> None:
    raw = json.loads(RAW.read_text())
    tx = raw['per_tx'][57]
    trace = tx['call_trace']
    helper = trace[45]['input']
    mint = trace[48]['input']
    transfer_from = trace[50]['input']
    mint_amount = word(mint, 1)
    token1_amount = word(transfer_from, 2)
    cashin = Decimal('5426.700593482696725462')
    cashout = Decimal(trace[99]['value']) / Decimal(10**18)
    artifact = {
        'status': 'DIAGNOSTIC_COUPLED_VIRTUAL_LIQUIDITY_DOSE_EXECUTED',
        'case_id': 'defihacklabs-veth-2024-11-14',
        'intervention': {
            'caller': '0x351d38733de3f1e73468d24401c59f63677000c9',
            'callee': '0x62f250cf7021e1cf76c765dec8ec623fe173a1b5',
            'selector': '0x6c0472da',
            'depth': 3,
            'action': 'rewrite_input',
            'original_helper_amount_raw': '300000000000000000000',
            'replacement_helper_amount_raw': str(mint_amount),
        },
        'coupling_observed': {
            'virtual_token_mint_raw': str(mint_amount),
            'lambo_token_transfer_from_raw': str(token1_amount),
            'lambo_token_transfer_from_tokens': str(Decimal(token1_amount) / Decimal(10**18)),
            'helper_input_rewrite_propagated_to_both_mint_legs': True,
        },
        'execution': {
            'actual_status': tx.get('actual_status'),
            'gas_match': tx.get('gas_match'),
            'status_match': tx.get('status_match'),
            'logs_match': tx.get('logs_match'),
            'post_state_match': tx.get('post_state_match'),
            'acceptance_gate': raw.get('acceptance_gate'),
            'intervention_application_verified': tx.get('call_intervention', {}).get('application_verified'),
        },
        'value_flow': {
            'cashin_eth_fixed': str(cashin),
            'cashout_eth': str(cashout),
            'cashout_minus_cashin_eth': str(cashout - cashin),
            'baseline_profit_eth': '4.846141416396402693',
            'profit_change_eth': str((cashout - cashin) - Decimal('4.846141416396402693')),
        },
        'interpretation': (
            'Coupled helper rewrite changed the virtual-token mint and proportional token1 '
            'pair.mint contribution together, while the transaction still executed. This is '
            'stronger dose sensitivity evidence than the uncoupled probe. It remains diagnostic '
            'only: logs/post-state differ by design and no claim-level causal verdict is authorized.'
        ),
        'raw_sha256': hashlib.sha256(RAW.read_bytes()).hexdigest(),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(artifact, indent=2) + '\n')
    print(OUT)
    print(hashlib.sha256(OUT.read_bytes()).hexdigest())

if __name__ == '__main__':
    main()
