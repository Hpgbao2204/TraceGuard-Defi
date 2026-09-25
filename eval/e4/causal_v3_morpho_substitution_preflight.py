"""Fail-closed preflight for the Alkimiya/Morpho capital substitution.

This deliberately does not mutate state or run a replay.  It records whether
the frozen historical context contains enough storage-bound evidence to
prefund the exact borrower without guessing a mapping slot.
"""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CTX = ROOT / "eval/results/m6/dependency-contexts/alkimiya"
OUT = ROOT / "eval/results/e4_causal_v3_morpho_substitution_preflight.json"

BORROWER = "0x80bf7db69556d9521c03461978b8fc731dbbd4e4"
PROVIDER = "0xbbbbbbbbbb9cc5e90e3b3af64bdaf62c37eeffcb"
ASSET = "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599"
PROVIDER_SELECTOR = "0xe0232b42"
CALLBACK_SELECTOR = "0x31f57072"
AMOUNT = 1_000_000_000  # WBTC has 8 decimals: 10 WBTC.


def main() -> None:
    tx = json.loads((CTX / "transactions.json").read_text())[0]
    pre = json.loads((CTX / "prestates.json").read_text())[0]["trace"]
    borrower = pre.get(BORROWER)
    asset = pre.get(ASSET)
    input_hex = tx["input"].lower()
    callback_present = CALLBACK_SELECTOR in input_hex
    provider_present = PROVIDER_SELECTOR in input_hex
    asset_present = ASSET in input_hex
    amount_present = f"{AMOUNT:064x}" in input_hex

    # Storage entries are proof material, not a mapping-slot proof.  Without
    # the verified Solidity layout or a balanceOf(slot) witness, writing any
    # one of these slots would be an unsupported state mutation.
    storage_entries = len((asset or {}).get("storage", {}))
    result = {
        "schema_version": 1,
        "status": "BLOCKED_MISSING_STORAGE_BOUND_PREFUND_PROOF",
        "replay_authorized": False,
        "capital_substitution_applied": False,
        "historical_transaction": tx["hash"],
        "chain_context": "ethereum",
        "provider": PROVIDER,
        "provider_selector": PROVIDER_SELECTOR,
        "borrower": BORROWER,
        "asset": ASSET,
        "amount_base_units": AMOUNT,
        "callback_selector": CALLBACK_SELECTOR,
        "historical_input_checks": {
            "provider_selector_present": provider_present,
            "callback_selector_present": callback_present,
            "asset_present": asset_present,
            "amount_present": amount_present,
        },
        "prestate_checks": {
            "borrower_present": borrower is not None,
            "asset_account_present": asset is not None,
            "asset_storage_entries_observed": storage_entries,
            "verified_balance_mapping_slot": False,
        },
        "required_before_replay": [
            "verified WBTC balanceOf mapping slot for the exact borrower",
            "provider-specific runtime adapter that preserves callback dispatch",
            "same-kind sham using the same instrumentation",
            "frozen no-undeclared-mutation postcondition",
        ],
        "reason": (
            "The frozen prestate exposes WBTC storage entries but does not bind "
            "any entry to balanceOf(borrower). Selecting a slot would be a "
            "guessed storage mutation; the generic intervention hook cannot "
            "both suppress provider capital and preserve the historical callback."
        ),
    }
    OUT.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "output": str(OUT)}))


if __name__ == "__main__":
    main()
