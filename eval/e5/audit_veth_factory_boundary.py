#!/usr/bin/env python3
import hashlib, json, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASE = ROOT / 'eval/results/m4/b2-contexts-fresh/defihacklabs-veth-2024-11-14'
OUT = ROOT / 'eval/results/e5_rcfh/veth_buyquote_dose_probe/factory_boundary_disassembly.json'
FACTORY = '0x19c5538df65075d53d6299904636bae68b6df441'

def main():
    pre = json.loads((CASE / 'prestates.json').read_text())[57]['trace']
    code = pre[FACTORY]['code']
    dis = subprocess.run(['cast', 'disassemble', code], check=True, capture_output=True, text=True).stdout.splitlines()
    wanted = {'000007ef','00000800','0000087d','0000089f','00000911','00000959'}
    hits = []
    for i, line in enumerate(dis):
        if any(line.startswith(pc + ':') for pc in wanted):
            hits.extend(dis[i:i+5])
    out = {
        'status': 'BOUNDARY_SEMANTICS_IDENTIFIED_OPERATOR_NOT_IMPLEMENTED',
        'case_id': 'defihacklabs-veth-2024-11-14',
        'factory': FACTORY,
        'selector': '0xa7591849',
        'dispatcher_target_pc': '0x07ef',
        'authenticated_factory_code_hash': pre[FACTORY]['codeHash'],
        'semantic_markers': {
            'pc_0x0800': 'CALLVALUE enters the function logic',
            'pc_0x087d': 'VirtualToken.cashIn() call construction',
            'pc_0x089f': 'VirtualToken.transfer() call construction',
            'pc_0x0911': 'UniswapV2Pair.swap() call construction',
            'pc_0x0959': 'amount/callvalue guard region',
        },
        'disassembly_excerpt': hits,
        'interpretation': 'The Factory boundary composes cashIn, token transfer, and pair swap. This is the executable root-boundary candidate; the helper mint call is a downstream manifestation inside this path.',
        'replay_authorized': False,
        'reason': 'A patched implementation with declared cost-settlement or reserve-consistency semantics is not yet materialized.',
        'source_sha256': hashlib.sha256((CASE / 'prestates.json').read_bytes()).hexdigest(),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2) + '\n')
    print(OUT)
    print(hashlib.sha256(OUT.read_bytes()).hexdigest())

if __name__ == '__main__': main()
