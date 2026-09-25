#!/usr/bin/env python3
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASE = ROOT / 'eval/results/m4/b2-contexts-fresh/defihacklabs-veth-2024-11-14'
OUT = ROOT / 'eval/results/e5_rcfh/veth_buyquote_dose_probe/call_nesting_boundary_audit.json'

def main():
    t = json.loads((CASE / 'b2-replay-m4.json').read_text())['per_tx'][57]['call_trace']
    rows = []
    for i in (17, 44, 45, 48, 64, 77):
        e = t[i]
        rows.append({k: e.get(k) for k in ('index','event','depth','type','from','to','input')})
    out = {
        'status': 'BOUNDARIES_SEPARATED',
        'case_id': 'defihacklabs-veth-2024-11-14',
        'factory_path': {
            'entry_index': 17,
            'exit_index': 44,
            'depth': 3,
            'selector': '0xa7591849',
            'interpretation': 'Factory cashIn/transfer/primary-swap path; trace 45 is not a descendant.'
        },
        'virtual_liquidity_path': {
            'entry_index': 45,
            'exit_index': 64,
            'depth': 3,
            'caller': '0x351d38733de3f1e73468d24401c59f63677000c9',
            'callee': '0x62f250cf7021e1cf76c765dec8ec623fe173a1b5',
            'selector': '0x6c0472da',
            'interpretation': 'Sibling call under the outer attacker contract; helper calls the mint-like VirtualToken operation and pair-side liquidity operation.'
        },
        'reverse_settlement_path': {'entry_index': 77, 'depth': 3, 'selector': '0xe784a059'},
        'boundary_decision': 'Trace 45 is the direct addVirtualLiquidity boundary candidate. Trace 17 is a separate enabling/primary-swap path, not the direct implementation site.',
        'evidence_rows': rows,
        'source_sha256': hashlib.sha256((CASE / 'b2-replay-m4.json').read_bytes()).hexdigest(),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2) + '\n')
    print(OUT)
    print(hashlib.sha256(OUT.read_bytes()).hexdigest())

if __name__ == '__main__': main()
