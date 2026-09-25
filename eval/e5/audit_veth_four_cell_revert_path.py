#!/usr/bin/env python3
"""Identify the first revert path in the VETH four-cell replay."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "eval/results/e5_rcfh/veth_buyquote_dose_probe/settlement_entry_storage_patch_real_four_cells.json"
OUT = ROOT / "eval/results/e5_rcfh/veth_buyquote_dose_probe/settlement_entry_storage_patch_four_cells_revert_path_audit.json"
PRESTATES = ROOT / "eval/results/m4/b2-contexts-fresh/defihacklabs-veth-2024-11-14/prestates.json"

WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
ATTACKER = "0x351d38733de3f1e73468d24401c59f63677000c9"
DEPOSIT_SELECTOR = "0xd0e30db0"


def main() -> None:
    data = json.loads(RAW.read_text())
    target = data["per_tx"][57]
    enters = [
        (i, e) for i, e in enumerate(target["call_trace"])
        if e.get("event") == "enter"
    ]
    failing = next(
        (i, e) for i, e in enters
        if e.get("to", "").lower() == WETH and e.get("input", "").lower() == DEPOSIT_SELECTOR
    )
    fail_index = failing[0]
    fail_exit = next(
        e for e in target["call_trace"][fail_index + 1:]
        if e.get("event") == "exit" and e.get("depth") == failing[1].get("depth")
    )
    value_raw = int(failing[1].get("value") or 0)
    assert failing[1].get("from", "").lower() == ATTACKER
    assert fail_exit.get("error") == "insufficient balance for transfer"

    # Reconstruct native balance from authenticated prestate plus every
    # nonzero CALL value entering/leaving the attacker before the failure.
    prestate = json.loads(PRESTATES.read_text())[57]["trace"]
    initial_balance = int(prestate[ATTACKER]["balance"], 16)
    ledger_balance = initial_balance
    ledger_events = []
    for i, event in enumerate(target["call_trace"][:fail_index]):
        if event.get("event") != "enter" or event.get("value") in (None, "0", 0, "<nil>"):
            continue
        amount = int(event["value"])
        sender = event.get("from", "").lower()
        recipient = event.get("to", "").lower()
        if sender == ATTACKER:
            ledger_balance -= amount
        if recipient == ATTACKER:
            ledger_balance += amount
        if sender == ATTACKER or recipient == ATTACKER:
            ledger_events.append({"call_trace_index": i, "from": event.get("from"), "to": event.get("to"), "value_raw_wei": str(amount)})
    shortfall = value_raw - ledger_balance

    reverse_pair_call = next(
        e for i, e in enters
        if e.get("input", "").lower().startswith("0x022c0d9f")
        and e.get("to", "").lower() == "0x582d17d24127cfdcbc8c4e0a40c12d77b2e7a48d"
    )
    cashout = next(
        (i, e) for i, e in enters
        if e.get("input", "").lower().startswith("0x5c7b79f5")
        and e.get("to", "").lower() == "0x280a8955a11fcd81d72ba1f99d265a48ce39ac2e"
    )
    cashout_amount = int(cashout[1]["input"][-64:], 16)
    attacker_receipt = next(
        (i, e) for i, e in enters
        if e.get("from", "").lower() == "0x19c5538df65075d53d6299904636bae68b6df441"
        and e.get("to", "").lower() == ATTACKER
        and int(e.get("value") or 0) == cashout_amount
    )
    assert cashout_amount == ledger_balance
    out = {
        "status": "REVERT_PATH_IDENTIFIED_DOWNSTREAM_WETH_REPAYMENT",
        "case_id": "defihacklabs-veth-2024-11-14",
        "raw_sha256": hashlib.sha256(RAW.read_bytes()).hexdigest(),
        "first_revert": {
            "call_trace_index": fail_index,
            "depth": failing[1]["depth"],
            "caller": failing[1]["from"],
            "callee": failing[1]["to"],
            "selector": DEPOSIT_SELECTOR,
            "function_role": "WETH.deposit()",
            "value_raw_wei": str(value_raw),
            "value_eth": f"{value_raw / 10**18:.18f}",
            "error": fail_exit["error"],
            "revert_data": fail_exit.get("output", "0x"),
        },
        "reverse_swap_context": {
            "pair_swap_present": True,
            "pair_swap_caller": reverse_pair_call.get("from"),
            "pair_swap_callee": reverse_pair_call.get("to"),
            "pair_swap_call_trace_index": next(i for i, e in enters if e is reverse_pair_call),
            "interpretation": "The four-cell replay reaches and passes the reverse pair.swap/token0-transfer stage; the first recorded failure is later at attacker-side WETH repayment preparation.",
        },
        "cashout_link": {
            "cashout_call_trace_index": cashout[0],
            "cashout_selector": "0x5c7b79f5",
            "cashout_amount_raw": str(cashout_amount),
            "cashout_amount_eth": f"{cashout_amount / 10**18:.18f}",
            "attacker_receipt_call_trace_index": attacker_receipt[0],
            "attacker_receipt_value_raw": str(int(attacker_receipt[1]["value"])),
            "matches_trace_derived_balance": True,
            "interpretation": "The patched reverse swap returns amount0Out to cashOut, which forwards the same 1.902689... ETH amount to the attacker before the failed WETH repayment call.",
        },
        "available_balance": {
            "raw_value_wei_trace_derived": str(ledger_balance),
            "eth_trace_derived": f"{ledger_balance / 10**18:.18f}",
            "shortfall_wei_trace_derived": str(shortfall),
            "shortfall_eth_trace_derived": f"{shortfall / 10**18:.18f}",
            "status": "TRACE_DERIVED_LEDGER_FROM_AUTHENTICATED_PRESTATE",
            "initial_balance_raw_wei": str(initial_balance),
            "ledger_events": ledger_events,
            "note": "This is a balance ledger reconstructed from authenticated prestate and all nonzero CALL values involving the attacker before trace 105; it is not an opcode-time balance snapshot.",
        },
        "classification": "INCONCLUSIVE_PRE_HARM_DOWNSTREAM_REPAYMENT_FAILURE",
        "not_causal_evidence": [
            "This is not a pair token0 transfer failure.",
            "It does not identify a fifth coupled storage cell.",
            "It does not by itself prove or disprove the timing-subsidy hypothesis.",
        ],
    }
    OUT.write_text(json.dumps(out, indent=2) + "\n")
    print(OUT)
    print(hashlib.sha256(OUT.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
