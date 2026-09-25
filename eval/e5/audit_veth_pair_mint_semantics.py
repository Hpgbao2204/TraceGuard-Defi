#!/usr/bin/env python3
import hashlib, json
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASE = ROOT / 'eval/results/m4/b2-contexts-fresh/defihacklabs-veth-2024-11-14'
OUT = ROOT / 'eval/results/e5_rcfh/veth_buyquote_dose_probe/pair_mint_semantics_audit.json'
PAIR = '0x582d17d24127cfdcbc8c4e0a40c12d77b2e7a48d'

def word(x, n): return int(x[2 + 64*n:2 + 64*(n+1)], 16)

def main():
    d = json.loads((CASE / 'b2-replay-m4.json').read_text())
    tx = d['per_tx'][57]
    t = tx['call_trace']
    mint_call = t[54]['input']
    mint_event = next((x for x in tx['logs'] if x['address'].lower() == PAIR and x['topics'][0].lower() == '0x4c209b5fc8ad50758f13e2e1088ba56a560dff690a1c6fef26394f4c03821c4f'), None)
    out = {
        'status': 'PAIR_MINT_SEMANTICS_OBSERVED',
        'case_id': 'defihacklabs-veth-2024-11-14',
        'pair_mint_call': {'trace_index': 54, 'selector': '0x6a627842', 'argument_to_raw': mint_call[-64:]},
        'pair_mint_event': {
            'present': mint_event is not None,
            'to_topic': mint_event['topics'][1] if mint_event else None,
            'amount0_raw': str(word(mint_event['data'], 0)) if mint_event else None,
            'amount1_raw': str(word(mint_event['data'], 1)) if mint_event else None,
            'amount0_token0': str(Decimal(word(mint_event['data'], 0))/Decimal(10**18)) if mint_event else None,
            'amount1_token1': str(Decimal(word(mint_event['data'], 1))/Decimal(10**18)) if mint_event else None,
        },
        'interpretation': 'The helper path performs a standard pair.mint-shaped operation after token0 mint and token1 transferFrom. The direct-donation/sync omission hypothesis is not supported. The causal question moves to LP recipient/accounting and whether virtual-liquidity minting is cost-consistent.',
        'operator_implication': 'A valid intervention must preserve pair.mint semantics while changing the declared virtual-liquidity accounting or cost-settlement rule. Do not insert sync or block pair.mint.',
        'replay_authorized': False,
        'source_sha256': hashlib.sha256((CASE / 'b2-replay-m4.json').read_bytes()).hexdigest(),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2) + '\n')
    print(OUT)
    print(hashlib.sha256(OUT.read_bytes()).hexdigest())

if __name__ == '__main__': main()
