#!/usr/bin/env python3
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASE = ROOT / 'eval/results/m4/b2-contexts-fresh/defihacklabs-veth-2024-11-14'
OUT = ROOT / 'eval/results/e5_rcfh/veth_buyquote_dose_probe/helper_provenance.json'
HELPER = '0x62f250cf7021e1cf76c765dec8ec623fe173a1b5'
OUTER = '0x351d38733de3f1e73468d24401c59f63677000c9'

def main():
    p = json.loads((CASE / 'prestates.json').read_text())[57]['trace']
    root = json.loads((CASE / 'b2-replay-m4.json').read_text())['per_tx'][57]['call_trace'][0]
    h, o = p[HELPER], p[OUTER]
    out = {
        'status': 'PROVENANCE_PARTIAL',
        'case_id': 'defihacklabs-veth-2024-11-14',
        'helper': {
            'address': HELPER,
            'present_in_authenticated_prestate': True,
            'nonce_before_target': h['nonce'],
            'code_bytes': (len(h['code']) - 2) // 2,
            'code_hash': h['codeHash'],
            'created_by_CREATE_in_target_trace': False,
        },
        'caller_chain': {
            'root_sender': root['from'],
            'outer_attacker_contract': OUTER,
            'outer_present_in_authenticated_prestate': True,
            'outer_nonce_before_target': o['nonce'],
            'root_to': root['to'],
        },
        'interpretation': {
            'established': 'The helper pre-existed the target transaction and was not created in it.',
            'not_established': 'Pre-existence alone does not prove protocol ownership; it may be an attacker-deployed contract from an earlier transaction.',
            'dose_policy': 'Proceed only as an attacker-path diagnostic unless ownership is independently established; rewrite only the mint call amount, not attacker capital.',
        },
        'source_sha256': {
            'prestates.json': hashlib.sha256((CASE / 'prestates.json').read_bytes()).hexdigest(),
            'b2-replay-m4.json': hashlib.sha256((CASE / 'b2-replay-m4.json').read_bytes()).hexdigest(),
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2) + '\n')
    print(OUT)
    print(hashlib.sha256(OUT.read_bytes()).hexdigest())

if __name__ == '__main__': main()
