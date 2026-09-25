#!/usr/bin/env python3
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = Path('/tmp/veth-cashin-alt-collateral.json')
OUT = ROOT / 'eval/results/e5_rcfh/veth_buyquote_dose_probe/cashin_alt_collateral_preflight.json'

def main():
    d = json.loads(RAW.read_text())
    t = d['per_tx'][57]
    out = {
        'status': 'NOT_TESTABLE_ALTERNATE_COLLATERAL_PRESTATE_INCOMPLETE',
        'case_id': 'defihacklabs-veth-2024-11-14',
        'intervention': {
            'kind': 'storage_override',
            'target': '0x280a8955a11fcd81d72ba1f99d265a48ce39ac2e',
            'slot': '0x07',
            'historical': '0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',
            'replacement': '0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2',
            'meaning': 'select collateral-token branch instead of native-ETH branch',
        },
        'replay_gates': {k: d.get(k) for k in ('acceptance_gate','all_status_match','all_gas_match','all_logs_match','relevant_post_state_match')},
        'target_result': {k: t.get(k) for k in ('expected_status','actual_status','status_match','gas_match','logs_match','post_state_match')},
        'failure_reasons': d.get('mutation_application'),
        'interpretation': 'Changing the collateral selector alone is not a valid alternative-collateral intervention. The historical transaction still sends native value to cashIn, while the alternate branch requires a complete authenticated ERC20 balance/allowance prestate and likely zero native value. No collateral-valid replay was authorized.',
        'raw_source': str(RAW),
        'raw_sha256': hashlib.sha256(RAW.read_bytes()).hexdigest(),
    }
    OUT.write_text(json.dumps(out, indent=2) + '\n')
    print(OUT)
    print(hashlib.sha256(OUT.read_bytes()).hexdigest())

if __name__ == '__main__': main()
