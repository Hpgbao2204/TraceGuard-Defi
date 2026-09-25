#!/usr/bin/env python3
"""Materialize a compact summary of the cashIn zero-mint diagnostic replay."""
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = Path('/tmp/veth-cashin-zero-mint.json')
OUT = ROOT / 'eval/results/e5_rcfh/veth_buyquote_dose_probe/cashin_zero_mint_replay.json'

def main():
    d = json.loads(RAW.read_text())
    t = d['per_tx'][57]
    events = []
    for e in t.get('call_trace', []):
        if e.get('event') == 'enter' or e.get('error'):
            events.append({k: e.get(k) for k in ('event','depth','type','from','to','input','value','error','reverted') if k in e})
    out = {
        'status': 'DIAGNOSTIC_NOT_CAUSAL_VERDICT',
        'case_id': 'defihacklabs-veth-2024-11-14',
        'intervention': {
            'kind': 'historical_runtime_code_override',
            'target': '0x280a8955a11fcd81d72ba1f99d265a48ce39ac2e',
            'pc': '0x0c60',
            'original': 'CALLVALUE',
            'replacement': 'PUSH0',
            'meaning': 'force cashIn mint amount to zero on observed native branch',
        },
        'replay_gates': {k: d.get(k) for k in ('acceptance_gate','all_status_match','all_gas_match','all_logs_match','relevant_post_state_match')},
        'target_result': {k: t.get(k) for k in ('expected_status','actual_status','status_match','gas_match','logs_match','post_state_match')},
        'call_trace_tail': events[-18:],
        'observed_effect': 'zero-mint intervention causes VirtualToken transfer to pair to revert before primary AMM swap; root transaction reverts and no token1 swap commit is observed',
        'allowed_interpretation': 'mint amount is necessary for this historical execution path to reach the swap and repayment sequence',
        'not_allowed': 'do not call this proof that cashIn policy is universally vulnerable or that minting is uncollateralized; the intervention deliberately forces an invalid zero amount',
        'raw_source': str(RAW),
        'raw_sha256': hashlib.sha256(RAW.read_bytes()).hexdigest(),
    }
    OUT.write_text(json.dumps(out, indent=2) + '\n')
    print(OUT)
    print(hashlib.sha256(OUT.read_bytes()).hexdigest())

if __name__ == '__main__': main()
