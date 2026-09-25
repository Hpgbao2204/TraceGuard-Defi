#!/usr/bin/env python3
import hashlib, json
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASE = ROOT / 'eval/results/m4/b2-contexts-fresh/defihacklabs-veth-2024-11-14'
OUT = ROOT / 'eval/results/e5_rcfh/veth_buyquote_dose_probe/virtual_liquidity_funding_audit.json'

def main():
    x = json.loads((CASE / 'b2-replay-m4.json').read_text())['per_tx'][57]
    raw = x['call_trace'][50]['input']
    source = '0x' + raw[10:74][-40:]
    destination = '0x' + raw[74:138][-40:]
    amount_raw = int(raw[138:202], 16)
    token1 = '0xab181941a6096296ecf1b0859ea65c797676d428'
    relevant = []
    for i, log in enumerate(x['logs']):
        if log['address'].lower() == token1:
            relevant.append({'log_index': i, 'from': '0x' + log['topics'][1][-40:], 'to': '0x' + log['topics'][2][-40:], 'amount': str(Decimal(int(log['data'], 16))/Decimal(10**18))})
    out = {
        'status': 'VIRTUAL_LIQUIDITY_FUNDED_FROM_ATTACKER_PATH',
        'case_id': 'defihacklabs-veth-2024-11-14',
        'transfer_from_calldata': {'trace_index': 50, 'source': source, 'destination': destination, 'amount_raw': str(amount_raw), 'amount_token1': str(Decimal(amount_raw)/Decimal(10**18))},
        'token1_transfer_ledger': relevant,
        'finding': 'The helper transferFrom source is the outer attacker contract, not a protocol treasury. The primary swap transfers a much larger token1 amount from the pair to the attacker before the helper path; the helper then moves 20264.412100062315020338 token1 from the attacker into the pair.',
        'causal_implication': 'This supports a sequencing/state-transition hypothesis, but does not by itself authorize a reorder intervention. A reorder must preserve the historical call semantics and define the synthetic state at the moved boundary.',
        'replay_authorized': False,
        'source_sha256': hashlib.sha256((CASE / 'b2-replay-m4.json').read_bytes()).hexdigest(),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2) + '\n')
    print(OUT)
    print(hashlib.sha256(OUT.read_bytes()).hexdigest())

if __name__ == '__main__': main()
