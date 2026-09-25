"""Illustrative arithmetic checks for Alkimiya discussion text.

NOT_PREREGISTERED — illustrative only, not counted in fixed-20.
This deliberately models only the observed shares/collateral arithmetic; it is
not a historical EVM replay and must not be consumed by verdict tooling.
"""
from __future__ import annotations

import json
from pathlib import Path

SHARES = 2**128 + 1
UINT128_MAX = 2**128 - 1
SCALE = 10**18


def main() -> None:
    rows = [
        {"technique": "clamp", "shares_used": UINT128_MAX,
         "shares_fit_uint128": True,
         "interpretation": "downstream collateral transfer still determines whether execution succeeds; if funded, mint amount is enormous"},
        {"technique": "scale_1e18", "shares_used": SHARES // SCALE,
         "shares_fit_uint128": True,
         "interpretation": "fits, but changes requested-share semantics; not a repair of the invalid source input"},
        {"technique": "skip", "shares_used": 0,
         "shares_fit_uint128": True,
         "interpretation": "no-op success model; avoids harm by omitting the operation, not by preserving mint semantics"},
    ]
    result = {
        "status": "NOT_PREREGISTERED — illustrative only, not counted in fixed-20",
        "input": "2^128 + 1",
        "input_integer": SHARES,
        "uint128_max": UINT128_MAX,
        "scale_divisor": SCALE,
        "scaled_value": SHARES // SCALE,
        "scaled_value_fits_uint128": SHARES // SCALE <= UINT128_MAX,
        "checks": rows,
        "limitation": "No collateral balance, provider trace, patched runtime, or state transition is simulated.",
    }
    out = Path(__file__).with_name("alkimiya_alternative_checks.json")
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
