#!/usr/bin/env python3
import hashlib, json
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = Path('/tmp/veth-mint-299.json')
OUT = ROOT / 'eval/results/e5_rcfh/veth_buyquote_dose_probe/mint_amount_299e18_uncoupled.json'

def main():
    d = json.loads(RAW.read_text())
    t = d['per_tx'][57]
    ct = t['call_trace']
    cashin = Decimal('5426.700593482696725462')
    cashout = Decimal(ct[99]['value']) / Decimal(10**18)
    residual = Decimal(ct[109]['value']) / Decimal(10**18)
    out = {
        'status': 'DIAGNOSTIC_UNCOUPLED_MINT_DOSE_EXECUTED',
        'case_id': 'defihacklabs-veth-2024-11-14',
        'dose': {'original_mint_raw': '300000000000000000000', 'replacement_mint_raw': '299000000000000000000', 'token1_transfer_held_fixed': '20264.412100062315020338'},
        'execution': {'actual_status': t.get('actual_status'), 'status_match': t.get('status_match'), 'gas_match': t.get('gas_match'), 'logs_match': t.get('logs_match'), 'post_state_match': t.get('post_state_match'), 'acceptance_gate': d.get('acceptance_gate')},
        'value_flow': {'cashin_eth': str(cashin), 'cashout_eth': str(cashout), 'residual_to_root_sender_eth': str(residual), 'profit_cashout_minus_cashin_eth': str(cashout-cashin)},
        'baseline_comparison': {'baseline_profit_eth': '4.846141416396402693', 'dose_profit_eth': str(cashout-cashin), 'profit_change_eth': str((cashout-cashin)-Decimal('4.846141416396402693'))},
        'interpretation': 'Reducing only the protocol-side mint from 300 to 299 token0 still executes and materially reduces the residual. This is strong diagnostic sensitivity evidence for the inter-swap mint, but it is not a causal verdict because token1 contribution was held fixed, changing the proportionality of the pair.mint deposit and causing non-identical logs/post-state.',
        'raw_sha256': hashlib.sha256(RAW.read_bytes()).hexdigest(),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2) + '\n')
    print(OUT)
    print(hashlib.sha256(OUT.read_bytes()).hexdigest())

if __name__ == '__main__': main()
