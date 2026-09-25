#!/usr/bin/env python3
"""Separate VETH pair inventory changes from attacker profit."""
import json
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASE = ROOT / 'eval/results/m4/b2-contexts-fresh/defihacklabs-veth-2024-11-14'
OUT = ROOT / 'eval/results/e5_rcfh/veth_buyquote_dose_probe/pair_lp_delta_audit.json'
PAIR = '0x582d17d24127cfdcbc8c4e0a40c12d77b2e7a48d'.lower()
TOKEN0 = '0x280a8955a11fcd81d72ba1f99d265a48ce39ac2e'.lower()
TOKEN1 = '0xab181941a6096296ecf1b0859ea65c797676d428'.lower()
TRANSFER = '0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef'

def topic_addr(x): return '0x' + x[-40:].lower()
def raw(x): return int(x, 16)
def dec(x): return str(Decimal(x) / Decimal(10**18))

def reserves(trace, indices):
    out = []
    for i in indices:
        e = trace[i]; nxt = next(x for x in trace[i+1:] if x.get('event') == 'exit' and x.get('depth') == e.get('depth'))
        data = nxt.get('output','')[2:]
        words = [int(data[j:j+64],16) for j in range(0, min(len(data),192),64)]
        out.append({'trace_index': i, 'reserve0_raw': str(words[0]), 'reserve1_raw': str(words[1]), 'reserve0': dec(words[0]), 'reserve1': dec(words[1])})
    return out

def main():
    d = json.loads((CASE / 'b2-replay-m4.json').read_text())
    tx = d['per_tx'][57]; trace = tx['call_trace']
    transfers = []
    for i,l in enumerate(tx.get('logs', [])):
        if l.get('topics',[None])[0] != TRANSFER or len(l.get('topics',[])) < 3: continue
        token = l['address'].lower()
        if token not in {TOKEN0,TOKEN1}: continue
        frm, to, amount = topic_addr(l['topics'][1]), topic_addr(l['topics'][2]), raw(l['data'])
        if frm == PAIR or to == PAIR:
            transfers.append({'log_index': i, 'token': token, 'from': frm, 'to': to, 'amount_raw': str(amount), 'amount': dec(amount), 'direction_for_pair': 'in' if to == PAIR else 'out'})
    net = {}
    for token in (TOKEN0, TOKEN1):
        ins = sum(int(x['amount_raw']) for x in transfers if x['token'] == token and x['direction_for_pair'] == 'in')
        outs = sum(int(x['amount_raw']) for x in transfers if x['token'] == token and x['direction_for_pair'] == 'out')
        net[token] = {'in_raw': str(ins), 'out_raw': str(outs), 'net_pair_balance_delta_raw': str(ins-outs), 'net_pair_balance_delta': dec(ins-outs)}
    initial = reserves(trace, [18])[0]
    initial_r0, initial_r1 = int(initial['reserve0_raw']), int(initial['reserve1_raw'])
    token1_net = int(net[TOKEN1]['net_pair_balance_delta_raw'])
    token0_net = int(net[TOKEN0]['net_pair_balance_delta_raw'])
    implied_token1_in_token0 = Decimal(initial_r0) / Decimal(initial_r1)
    implied = {
        'price_token1_in_token0': str(implied_token1_in_token0),
        'token1_net_delta_valued_in_token0_raw': str(Decimal(token1_net) * implied_token1_in_token0),
        'token1_net_delta_valued_in_token0': str((Decimal(token1_net) * implied_token1_in_token0) / Decimal(10**18)),
        'token0_net_delta': dec(token0_net),
        'net_pair_delta_valued_in_token0': str((Decimal(token0_net) + Decimal(token1_net) * implied_token1_in_token0) / Decimal(10**18)),
        'note': 'Uses pre-attack getReserves snapshot only; this is a diagnostic mark-to-initial-price, not a causal LP valuation.'
    }
    post_pair = json.loads((CASE / 'poststates.json').read_text())[57]['poststate'][PAIR]
    packed = int(post_pair['storage']['0x' + '0'*63 + '8'], 16)
    mask = (1 << 112) - 1
    final_r0, final_r1, final_ts = packed & mask, (packed >> 112) & mask, packed >> 224
    initial_r0_d, initial_r1_d = Decimal(initial_r0), Decimal(initial_r1)
    final_r0_d, final_r1_d = Decimal(final_r0), Decimal(final_r1)
    k_initial, k_final = initial_r0_d * initial_r1_d, final_r0_d * final_r1_d
    out = {
        'status': 'DIAGNOSTIC_PAIR_INVENTORY_AUDIT',
        'case_id': 'defihacklabs-veth-2024-11-14',
        'pair': PAIR, 'token0': TOKEN0, 'token1': TOKEN1,
        'reserve_snapshots': reserves(trace, [18,46,82]),
        'pair_related_transfer_logs': transfers,
        'aggregate_pair_balance_delta_from_transfer_logs': net,
        'poststate_packed_reserves': {'storage_slot': '0x08', 'timestamp': final_ts, 'reserve0_raw': str(final_r0), 'reserve1_raw': str(final_r1), 'reserve0': dec(final_r0), 'reserve1': dec(final_r1)},
        'invariant_check': {'k_initial_raw_product': str(k_initial), 'k_final_raw_product': str(k_final), 'k_final_over_k_initial': str(k_final / k_initial)},
        'implied_initial_price_check': implied,
        'interpretation': {
            'primary_swap': 'The first pair Swap is represented by token0/token1 Transfer logs near primary execution; use reserve snapshots and directions, not attacker profit, for pool inventory analysis.',
            'reverse_swap': 'The later reverse settlement transfers the opposite token into the pair and returns token0; this can change inventory without being equivalent to a direct LP loss.',
            'timing': 'Snapshot trace 82 occurs before cashOut trace 98. Therefore it is pre-cashOut reserve state, not final post-transaction reserves. The later token0 cashOut transfer must be analyzed as an actual-balance change and not silently applied to the reserve snapshot.',
            'same_pair_check': 'All included token Transfer logs are filtered against the same pair address 0x582d17...a48d.',
            'not_yet_claimed': 'No LP harm verdict is issued from inventory deltas alone; LP share ownership, fees, and fair-value baseline are still required.'
        }
    }
    OUT.parent.mkdir(parents=True, exist_ok=True); OUT.write_text(json.dumps(out,indent=2)+'\n'); print(OUT)
    print(json.dumps(out['reserve_snapshots'],indent=2)); print(json.dumps(transfers,indent=2))

if __name__ == '__main__': main()
