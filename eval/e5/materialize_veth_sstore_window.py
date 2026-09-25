#!/usr/bin/env python3
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = Path('/tmp/veth-sstore-baseline-v4.json')
BASE = ROOT / 'eval/results/m4/b2-contexts-fresh/defihacklabs-veth-2024-11-14'
OUT = ROOT / 'eval/results/e5_rcfh/veth_buyquote_dose_probe/helper_window_sstore_write_set.json'
PAIR = '0x582d17d24127cfdcbc8c4e0a40c12d77b2e7a48d'
TOKEN0 = '0x280a8955a11fcd81d72ba1f99d265a48ce39ac2e'
TOKEN1 = '0xab181941a6096296ecf1b0859ea65c797676d428'

def main():
    d = json.loads(RAW.read_text())
    ops = [x for x in d['per_tx'][57]['opcode_tail'] if x.get('op') == 'SSTORE' and 45 <= x.get('call_trace_index', -1) <= 64]
    pre = json.loads((BASE / 'prestates.json').read_text())[57]['trace']
    pair_pre = pre[PAIR]['storage'].get('0x' + '0' * 63 + '8')
    relevant = [x for x in ops if x.get('storage_context', '').lower() in {PAIR, TOKEN0, TOKEN1}]
    candidate, excluded = [], []
    for x in relevant:
        ctx, slot = x['storage_context'].lower(), x['storage_slot']
        item = {'call_trace_index': x['call_trace_index'], 'pc': x['pc'], 'depth': x['depth'], 'storage_context': ctx, 'slot': slot, 'value_after_sstore': x['storage_value']}
        if (ctx == PAIR and int(slot, 0) == 8) or (ctx in {TOKEN0, TOKEN1}):
            candidate.append(item)
        else:
            excluded.append(item)
    token0_entry = next(x for x in relevant if x['storage_context'].lower() == TOKEN0 and x['storage_value'] == '5751708384988506275997')
    token1_entry = next(x for x in relevant if x['storage_context'].lower() == TOKEN1 and x['storage_value'] == '388516629975969875884099')
    token0_slot = token0_entry['storage_slot']; token1_slot = token1_entry['storage_slot']
    token0_pre = pre[TOKEN0]['storage'].get('0x' + format(int(token0_slot), '064x'))
    token1_pre = pre[TOKEN1]['storage'].get('0x' + format(int(token1_slot), '064x'))
    out = {'status': 'HELPER_WINDOW_WRITE_SET_ISOLATED_STORAGE_PATCH_CANDIDATE', 'case_id': 'defihacklabs-veth-2024-11-14', 'window': {'start_call_trace_index': 45, 'end_call_trace_index': 64, 'pair_mint_call_trace_index': 54}, 'all_relevant_sstores': relevant, 'candidate_pricing_state_writes': candidate, 'excluded_lp_or_bookkeeping_writes': excluded, 'pre_helper_values': {'pair_slot_0x8': pair_pre, 'token0_pair_balance_slot': token0_slot, 'token0_pair_balance_before': token0_pre, 'token1_pair_balance_slot': token1_slot, 'token1_pair_balance_before': token1_pre}, 'patch_scope': {'pair_slot_0x8': pair_pre, 'token0_pair_balance_mapping': {'slot': token0_slot, 'before': token0_pre}, 'token1_pair_balance_mapping': {'slot': token1_slot, 'before': token1_pre}}, 'interpretation': 'The helper-window SSTORE telemetry isolates pair.mint and preceding token balance writes. The reverse swap reads packed pair reserves and live token balances; LP supply/accounting writes are excluded from the timing patch. This is a patch candidate only; an explicit call-site storage-patch primitive and same-kind sham are still required.', 'raw_sha256': hashlib.sha256(RAW.read_bytes()).hexdigest()}
    OUT.write_text(json.dumps(out, indent=2) + '\n')
    print(OUT)
    print(hashlib.sha256(OUT.read_bytes()).hexdigest())

if __name__ == '__main__':
    main()
