#!/usr/bin/env python3
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = Path('/tmp/veth-block-mint-call.json')
OUT = ROOT / 'eval/results/e5_rcfh/veth_buyquote_dose_probe/mint_call_block_replay.json'

def main():
    d = json.loads(RAW.read_text())
    t = d['per_tx'][57]
    out = {
        'status': 'INCONCLUSIVE_BLOCKING_MINT_CALL',
        'case_id': 'defihacklabs-veth-2024-11-14',
        'intervention': t.get('call_intervention'),
        'replay_gates': {k: d.get(k) for k in (
            'acceptance_gate', 'all_status_match', 'all_gas_match',
            'all_logs_match', 'relevant_post_state_match')},
        'target_result': {k: t.get(k) for k in (
            'expected_status', 'actual_status', 'status_match', 'gas_match',
            'logs_match', 'post_state_match')},
        'interpretation': (
            'Blocking the exact helper-to-VirtualToken call with selector '
            '0x9e358be1 matched once at depth 4 and reverted the root '
            'transaction before reverse settlement. The historical calldata '
            'decodes as destination=the pair and amount=300 token0. This '
            'isolates the mint-like call as necessary for this execution '
            'path, but does not yet distinguish authorization, mint amount, '
            'helper sequencing, or another helper side effect. It is '
            'dependency evidence, not a root-cause verdict.'
        ),
        'raw_sha256': hashlib.sha256(RAW.read_bytes()).hexdigest(),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2) + '\n')
    print(OUT)
    print(hashlib.sha256(OUT.read_bytes()).hexdigest())

if __name__ == '__main__':
    main()
