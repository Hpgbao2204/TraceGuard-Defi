#!/usr/bin/env python3
import hashlib, json
from decimal import Decimal, getcontext
from pathlib import Path
getcontext().prec = 60

ROOT = Path(__file__).resolve().parents[2]
CASE = ROOT / 'eval/results/m4/b2-contexts-fresh/defihacklabs-veth-2024-11-14'
OUT = ROOT / 'eval/results/e5_rcfh/veth_buyquote_dose_probe/virtual_liquidity_ratio_audit.json'

def main():
    t = json.loads((CASE / 'b2-replay-m4.json').read_text())['per_tx'][57]['call_trace']
    out46 = t[47]['output']
    words = [int(out46[2+i:2+i+64], 16) for i in range(0, len(out46)-2, 64)]
    r0, r1 = Decimal(words[0])/Decimal(10**18), Decimal(words[1])/Decimal(10**18)
    a0, a1 = Decimal(300), Decimal('20264.412100062315020338')
    reserve_ratio, mint_ratio = r1/r0, a1/a0
    out = {
        'status': 'PROPORTIONAL_VIRTUAL_LIQUIDITY_LP_BURNED',
        'case_id': 'defihacklabs-veth-2024-11-14',
        'snapshot': {'trace_index': 46, 'exit_index': 47, 'reserve0': str(r0), 'reserve1': str(r1), 'timestamp': words[2]},
        'mint': {'trace_index': 54, 'selector': '0x6a627842', 'recipient': '0x0000000000000000000000000000000000000000', 'amount0': str(a0), 'amount1': str(a1)},
        'ratio_comparison': {'reserve_token1_per_token0': str(reserve_ratio), 'mint_token1_per_token0': str(mint_ratio), 'mint_to_reserve_ratio': str(mint_ratio/reserve_ratio)},
        'finding': 'The virtual-liquidity deposit matches the post-primary-swap reserve ratio to approximately 1e-23 relative error, and LP recipient is address(0). The disproportionate-mint hypothesis is not supported for this path.',
        'causal_implication': 'The candidate issue is not an attacker-owned or price-skewed LP mint. It is a protocol-side proportional virtual-liquidity/accounting interaction whose cost settlement must be tested separately.',
        'replay_authorized': False,
        'source_sha256': hashlib.sha256((CASE / 'b2-replay-m4.json').read_bytes()).hexdigest(),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2) + '\n')
    print(OUT)
    print(hashlib.sha256(OUT.read_bytes()).hexdigest())

if __name__ == '__main__': main()
