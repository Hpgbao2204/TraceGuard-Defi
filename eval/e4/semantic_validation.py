"""Evidence-bound semantic checks for interventions."""

from __future__ import annotations

import re
from collections.abc import Collection
from dataclasses import dataclass


_HEX_SELECTOR = re.compile(r"^[0-9a-fA-F]{8}$")

# Populated per protocol/case when an oracle intervention is admitted.  An
# empty entry is intentional: callers that provide ``protocol_id`` fail
# closed instead of treating an arbitrary contract with a matching return
# shape as an approved oracle.
PROTOCOL_ORACLE_REGISTRY: dict[str, frozenset[str]] = {}


@dataclass(frozen=True)
class PriceValue:
    """Decoded price with the unit metadata required for comparison."""

    value: int
    decimals: int
    quote_currency: str


def compare_reference_price(reference: PriceValue, observed: PriceValue) -> tuple[str, str]:
    """Reject deltas across incompatible decimals or quote currencies."""
    if reference.decimals != observed.decimals:
        return "invalid", "oracle-price-unit-mismatch-decimals"
    if reference.quote_currency.upper() != observed.quote_currency.upper():
        return "invalid", "oracle-price-unit-mismatch-quote-currency"
    return "valid", "oracle-price-units-match"


def _normalise_hex(value: str) -> str | None:
    text = str(value or "")
    if not text.startswith("0x") or len(text) % 2:
        return None
    body = text[2:]
    if any(char not in "0123456789abcdefABCDEF" for char in body):
        return None
    return "0x" + body.lower()


def oracle_postcondition(payload: dict, *, oracle: str, selector: str,
                         expected_return: str | None = None,
                         reference_verified: bool = False,
                         protocol_id: str | None = None,
                         allowed_oracles: Collection[str] | None = None,
                         reference_price: PriceValue | None = None,
                         observed_price: PriceValue | None = None) -> tuple[str, str]:
    """Check that the targeted getter was reached and returned expected data.

    A getter hit without an expected historical return is observable evidence,
    not a valid semantic contract. The caller must supply the pre-mutation
    ``eth_call`` result when promoting this check to ``valid``.
    """
    target = payload.get("per_tx", [])
    if not isinstance(target, list):
        return "invalid", "per-tx-trace-missing"
    try:
        index = int(payload.get("target_index", len(target) - 1))
    except (TypeError, ValueError):
        return "invalid", "target-index-malformed"
    result = target[index] if 0 <= index < len(target) else {}
    if not isinstance(result, dict):
        return "invalid", "target-trace-malformed"
    frames = result.get("call_trace") or []
    if not isinstance(frames, list):
        return "invalid", "call-trace-malformed"
    if any(not isinstance(frame, dict) for frame in frames):
        return "invalid", "call-trace-frame-malformed"
    wanted = selector.lower().removeprefix("0x")
    if not _HEX_SELECTOR.fullmatch(wanted):
        return "invalid", "oracle-selector-malformed"
    oracle_address = str(oracle or "").lower()
    if not oracle_address:
        return "invalid", "oracle-target-missing"
    registry = allowed_oracles
    if registry is None and protocol_id is not None:
        registry = PROTOCOL_ORACLE_REGISTRY.get(protocol_id.lower(), frozenset())
    if registry is not None and oracle_address not in {str(item).lower() for item in registry}:
        return "invalid", "oracle-address-not-in-registry"
    hits = []
    for pos, frame in enumerate(frames):
        if frame.get("event") != "enter":
            continue
        if str(frame.get("to", "")).lower() != oracle_address:
            continue
        calldata = str(frame.get("input", "")).lower().removeprefix("0x")
        if not calldata.startswith(wanted) or len(calldata) < 8:
            continue
        depth = frame.get("depth")
        exit_frame = None
        malformed = False
        for item in frames[pos + 1:]:
            if item.get("event") == "enter" and item.get("depth") == depth:
                malformed = True
                break
            if item.get("event") == "exit" and item.get("depth") == depth:
                exit_frame = item
                break
        if malformed:
            exit_frame = None
        hits.append((frame, exit_frame))
    if not hits:
        return "invalid", "oracle-getter-not-reached"
    if any(exit_frame is None or exit_frame.get("reverted") or exit_frame.get("error")
           for _, exit_frame in hits):
        return "invalid", "oracle-getter-reverted-or-unclosed"
    if expected_return is None:
        return "unknown", "oracle-reference-return-missing"
    expected = _normalise_hex(expected_return)
    if expected is None:
        return "invalid", "oracle-reference-return-malformed"
    if reference_verified is not True:
        return "unknown", "oracle-reference-unverified"
    if reference_price is not None or observed_price is not None:
        if reference_price is None or observed_price is None:
            return "unknown", "oracle-price-metadata-incomplete"
        unit_status, unit_reason = compare_reference_price(reference_price, observed_price)
        if unit_status != "valid":
            return unit_status, unit_reason
    if any(str(exit_frame.get("output", "")).lower() != expected
           for _, exit_frame in hits):
        return "invalid", "oracle-return-mismatch"
    return "valid", "oracle-getter-postcondition-verified"


def flash_loan_postcondition(payload: dict, *, provider: str,
                             selector: str) -> tuple[str, str]:
    """Verify that the declared flash-loan entrypoint was actually blocked.

    This establishes application/semantic validity of ``f_fl`` only.  A
    reverted transaction remains non-comparable for causal scoring and is
    handled separately by the execution-validity gate.
    """
    target = payload.get("per_tx", [])
    if not isinstance(target, list):
        return "invalid", "per-tx-trace-missing"
    try:
        index = int(payload.get("target_index", len(target) - 1))
    except (TypeError, ValueError):
        return "invalid", "target-index-malformed"
    result = target[index] if 0 <= index < len(target) else {}
    if not isinstance(result, dict):
        return "invalid", "target-trace-malformed"
    wanted = str(selector or "").lower().removeprefix("0x")
    if not _HEX_SELECTOR.fullmatch(wanted):
        return "invalid", "flash-selector-malformed"
    target_address = str(provider or "").lower()
    if not target_address:
        return "invalid", "flash-provider-missing"
    frames = result.get("call_trace") or []
    if not isinstance(frames, list) or any(not isinstance(frame, dict) for frame in frames):
        return "invalid", "call-trace-malformed"
    hits: list[tuple[dict, dict | None]] = []
    for pos, frame in enumerate(frames):
        if frame.get("event") != "enter":
            continue
        if str(frame.get("to", "")).lower() != target_address:
            continue
        calldata = str(frame.get("input") or "").lower().removeprefix("0x")
        if not calldata.startswith(wanted):
            continue
        depth = frame.get("depth")
        exit_frame = next((item for item in frames[pos + 1:]
                           if item.get("event") == "exit" and item.get("depth") == depth), None)
        hits.append((frame, exit_frame))
    if not hits:
        return "invalid", "flash-entrypoint-not-reached"
    if any(exit_frame is None for _, exit_frame in hits):
        return "invalid", "flash-entrypoint-unclosed"
    if any(not (exit_frame.get("reverted") or exit_frame.get("error"))
           for _, exit_frame in hits if exit_frame is not None):
        return "invalid", "flash-entrypoint-not-blocked"
    return "valid", "flash-entrypoint-blocked"
