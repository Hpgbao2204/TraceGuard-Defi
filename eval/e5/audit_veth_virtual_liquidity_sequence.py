#!/usr/bin/env python3
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASE = ROOT / 'eval/results/m4/b2-contexts-fresh/defihacklabs-veth-2024-11-14'
OUT = ROOT / 'eval/results/e5_rcfh/veth_buyquote_dose_probe/virtual_liquidity_sequence_audit.json'

def main():
    t = json.loads((CASE / 'b2-replay-m4.json').read_text())['per_tx'][57]['call_trace']
    seq = []
    for i in range(45, 65):
        e = t[i]
        if e.get('event') == 'enter':
            seq.append({'index': i, 'depth': e.get('depth'), 'type': e.get('type'), 'from': e.get('from'), 'to': e.get('to'), 'selector': (e.get('input') or '')[:10]})
    out = {
        'status': 'MINT_AND_PAIR_MINT_OBSERVED_NOT_DONATION_ONLY',
        'case_id': 'defihacklabs-veth-2024-11-14',
        'selector_0x6a627842': 'UniswapV2Pair.mint(address)',
        'selector_0xfff6cae9': 'UniswapV2Pair.sync()',
        'observed_sequence': seq,
        'finding': 'The helper first reads reserves, performs the VirtualToken mint-like call, pulls token1 with transferFrom, then calls pair.mint(address). No sync() call is observed in this frame.',
        'consequence': 'The simple donation-only hypothesis (direct token0 transfer without pair.mint) is falsified for this historical path. A sync-only operator would not model the observed operation.',
        'operator_implication': 'The next intervention must model the semantics of pair.mint and virtual-liquidity accounting, not merely insert sync or block the helper.',
        'replay_authorized': False,
        'source_sha256': hashlib.sha256((CASE / 'b2-replay-m4.json').read_bytes()).hexdigest(),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2) + '\n')
    print(OUT)
    print(hashlib.sha256(OUT.read_bytes()).hexdigest())

if __name__ == '__main__': main()
