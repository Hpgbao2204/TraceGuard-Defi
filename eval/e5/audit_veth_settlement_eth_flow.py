#!/usr/bin/env python3
"""Materialize the VETH settlement/cashOut ETH flow from the canonical trace."""
import json
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASE = ROOT / 'eval/results/m4/b2-contexts-fresh/defihacklabs-veth-2024-11-14'
OUT = ROOT / 'eval/results/e5_rcfh/veth_buyquote_dose_probe/settlement_eth_flow.json'
FACTORY = '0x19c5538df65075d53d6299904636bae68b6df441'
VIRTUAL = '0x280a8955a11fcd81d72ba1f99d265a48ce39ac2e'
LAMBO = '0xab181941a6096296ecf1b0859ea65c797676d428'
WETH = '0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2'

def eth(x): return str(Decimal(x) / Decimal(10**18))
def amount(input_hex): return int(input_hex[-64:], 16)

def main():
    trace = json.loads((CASE / 'b2-replay-m4.json').read_text())['per_tx'][57]['call_trace']
    e77 = trace[77]; e78 = trace[78]; e84 = trace[84]; e88 = trace[88]; e98 = trace[98]; e99 = trace[99]; e102 = trace[102]; e105 = trace[105]; e109 = trace[109]
    cashout_amount = amount(e98['input'])
    lambo_in = amount(e78['input'])
    vtoken_out = amount(e88['input'])
    cashout_eth = int(e99['value'])
    buy_eth = int(e105['value'])
    profit = int(e109['value'])
    out = {
        'status': 'DIAGNOSTIC_VALUE_FLOW',
        'case_id': 'defihacklabs-veth-2024-11-14',
        'trace_indices': {'settlement_entry': 77, 'lambo_transfer_to_factory': 78, 'lambo_to_pair': 84, 'reverse_swap': 88, 'cashOut': 98, 'cashOut_eth_to_factory': 99, 'eth_to_flashloan_caller': 102, 'weth_repay_deposit': 105, 'profit_to_attacker': 109},
        'addresses': {'factory': FACTORY, 'virtual_token': VIRTUAL, 'lambo_token': LAMBO, 'weth': WETH},
        'selectors': {'settlement_entry': '0xe784a059', 'transferFrom': '0x23b872dd', 'transfer': '0xa9059cbb', 'swap': '0x022c0d9f', 'cashOut': '0x5c7b79f5', 'weth_deposit': '0xd0e30db0'},
        'raw_values': {'lambo_to_factory': str(lambo_in), 'cashOut_virtual_amount': str(cashout_amount), 'cashOut_eth': str(cashout_eth), 'weth_repay_amount': str(buy_eth), 'profit_to_attacker': str(profit)},
        'eth_values': {'cashOut_eth': eth(cashout_eth), 'weth_repay': eth(buy_eth), 'profit_to_attacker': eth(profit), 'cashOut_minus_repay': eth(cashout_eth - buy_eth)},
        'checks': {'cashOut_eth_equals_caller_funding': cashout_eth == int(e102['value']), 'profit_equals_cashout_minus_repay': profit == cashout_eth - buy_eth, 'root_tx_completed': trace[-1].get('event') == 'exit' and not trace[-1].get('reverted', False)},
        'interpretation': 'Trace 77 is a reverse settlement path: LamboToken is swapped back into VirtualToken, cashOut converts VirtualToken to native ETH, the Factory funds flash-loan repayment, and the residual 4.846141416396403 ETH is sent to the attacker. This is value-flow evidence, not yet a causal root-cause verdict.',
        'limitation': 'Reported attacker profit is not by itself the protected-harm definition; the causal claim must specify whether the protected boundary is Factory/LP ETH, the pool reserve, or an accounting invariant.',
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2) + '\n')
    print(OUT)
    print(json.dumps(out['eth_values'], indent=2))

if __name__ == '__main__': main()
