"""Typed protected-harm adapters for supplementary causal readiness.

These adapters measure only the preregistered protected entity.  They never use
attacker profit as a proxy for protocol harm.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from eval.e4.harm import _finite_nonnegative, _native_balance_delta, _token_transfer_delta
from eval.e4.models import HarmAssessment


def _provenance_error(spec: dict[str, Any], key: str) -> str | None:
    ref = spec.get("price_reference_block")
    target = spec.get("target_block")
    records = spec.get("price_provenance")
    if not isinstance(ref, int) or not isinstance(target, int) or target <= ref:
        return "price reference must precede target block"
    if not isinstance(records, dict):
        return "price provenance records missing"
    record = records.get(key) or records.get(key.lower())
    if not isinstance(record, dict) or record.get("reference_block") != ref:
        return f"price provenance missing for {key}"
    if not isinstance(record.get("source"), str) or not record["source"].strip():
        return f"price provenance source missing for {key}"
    return None


def _threshold(spec: dict[str, Any]) -> tuple[float, float] | str:
    price = _finite_nonnegative(spec.get("usd_per_token"))
    threshold = _finite_nonnegative(spec.get("lmin_usd"))
    if price is None or threshold is None:
        return "price or Lmin is missing/invalid"
    return price, threshold


def assess_xloot_native_eth(target: dict, spec: dict[str, Any]) -> HarmAssessment:
    """Measure native ETH debit of the preregistered XLoot entity."""
    owner = str(spec.get("protected_entity") or "").lower()
    if not owner:
        return HarmAssessment("UNKNOWN", source="xloot_native_eth", reason="protected entity missing")
    if str(spec.get("asset_kind", "")).lower() not in {"native", "native_eth", "eth"}:
        return HarmAssessment("UNKNOWN", source="xloot_native_eth", reason="asset is not native ETH")
    price_result = _threshold(spec)
    if isinstance(price_result, str):
        return HarmAssessment("UNKNOWN", source="xloot_native_eth", reason=price_result)
    price, threshold = price_result
    provenance = _provenance_error(spec, "native_eth")
    if provenance:
        return HarmAssessment("UNKNOWN", source="xloot_native_eth", reason=provenance)
    delta = _native_balance_delta(target, owner)
    if delta is None:
        return HarmAssessment("UNKNOWN", source="xloot_native_eth", reason="protected native balance observation missing")
    loss = float(max(0, -delta) / Decimal(10**18) * Decimal(str(price)))
    return HarmAssessment("HARM" if loss > threshold else "NO_HARM", loss,
                          "protected_native_balance_delta",
                          f"owner={owner}; delta_wei={delta}; Lmin={threshold}")


def assess_alkimiya_wbtc(target: dict, spec: dict[str, Any]) -> HarmAssessment:
    """Measure preregistered protected-entity WBTC Transfer-ledger debit."""
    owner = str(spec.get("protected_entity") or "").lower()
    token = str(spec.get("asset_address") or "").lower()
    if not owner or not token:
        return HarmAssessment("UNKNOWN", source="alkimiya_wbtc", reason="protected entity or WBTC address missing")
    if str(spec.get("asset_kind", "erc20")).lower() != "erc20":
        return HarmAssessment("UNKNOWN", source="alkimiya_wbtc", reason="asset is not ERC-20")
    price_result = _threshold(spec)
    if isinstance(price_result, str):
        return HarmAssessment("UNKNOWN", source="alkimiya_wbtc", reason=price_result)
    price, threshold = price_result
    provenance = _provenance_error(spec, "wbtc")
    if provenance:
        return HarmAssessment("UNKNOWN", source="alkimiya_wbtc", reason=provenance)
    decimals = spec.get("decimals", 8)
    try:
        decimals = int(decimals)
    except (TypeError, ValueError):
        return HarmAssessment("UNKNOWN", source="alkimiya_wbtc", reason="invalid WBTC decimals")
    delta = _token_transfer_delta(target, owner, token)
    if delta is None:
        return HarmAssessment("UNKNOWN", source="alkimiya_wbtc", reason="protected WBTC Transfer observation missing")
    loss = float(max(0, -delta) / Decimal(10**decimals) * Decimal(str(price)))
    return HarmAssessment("HARM" if loss > threshold else "NO_HARM", loss,
                          "protected_erc20_transfer_delta",
                          f"owner={owner}; token={token}; delta_base_units={delta}; Lmin={threshold}")
