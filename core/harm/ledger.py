"""Fail-closed, Decimal-valued protected harm ledger."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Mapping


class HarmStatus(StrEnum):
    NO_HARM = "NO_HARM"
    HARM = "HARM"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class HarmSpecification:
    """Frozen valuation contract for one protected objective."""

    victims: frozenset[str]
    assets: Mapping[str, tuple[int, Decimal]]
    threshold: Decimal
    measure: str = "net_asset_loss"
    required_assets: frozenset[str] | None = None
    required_liabilities: frozenset[str] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.threshold, Decimal) or not self.threshold.is_finite() or self.threshold < 0:
            raise ValueError("threshold must be non-negative")
        if self.measure not in {"net_asset_loss", "pool_debit", "liability_lower_bound"}:
            raise ValueError("unsupported harm measure")
        if self.required_assets is not None and not self.required_assets:
            raise ValueError("required_assets must not be empty when provided")
        if self.required_liabilities is not None and not self.required_liabilities:
            raise ValueError("required_liabilities must not be empty when provided")


@dataclass(frozen=True)
class HarmAssessment:
    status: HarmStatus
    value: Decimal | None
    reason: str


def assess_ledger(
    specification: HarmSpecification,
    asset_deltas: Mapping[str, Mapping[str, int]],
    liabilities: Mapping[str, Mapping[str, int]] | None = None,
) -> HarmAssessment:
    """Value signed raw-unit deltas; missing valuation never becomes zero."""
    victims = {address.lower() for address in specification.victims}
    if not victims:
        return HarmAssessment(HarmStatus.UNKNOWN, None, "no protected victims")
    required_assets = {a.lower() for a in (specification.required_assets or specification.assets)}
    required_liabilities = {
        a.lower() for a in (specification.required_liabilities or required_assets)
    }
    if specification.measure == "net_asset_loss" and liabilities is None:
        return HarmAssessment(HarmStatus.UNKNOWN, None, "liability observations required for net asset loss")
    liability_data = liabilities or {}

    def _owner_changes(source: Mapping[str, Mapping[str, int]], owner: str) -> Mapping[str, int] | None:
        for candidate, changes in source.items():
            if candidate.lower() == owner:
                return changes
        return None

    # A mapping entry is an observation record, not merely an optional input.
    # Every protected owner and required cell must be present; absent cells are
    # UNKNOWN rather than implicit zero.
    for owner in victims:
        assets_for_owner = _owner_changes(asset_deltas, owner)
        if assets_for_owner is None or not required_assets.issubset(
                {str(asset).lower() for asset in assets_for_owner}):
            return HarmAssessment(HarmStatus.UNKNOWN, None,
                                  f"incomplete protected asset observations for {owner}")
        if specification.measure == "net_asset_loss":
            liabilities_for_owner = _owner_changes(liability_data, owner)
            if liabilities_for_owner is None or not required_liabilities.issubset(
                    {str(asset).lower() for asset in liabilities_for_owner}):
                return HarmAssessment(HarmStatus.UNKNOWN, None,
                                      f"incomplete liability observations for {owner}")
    total_loss = Decimal("0")
    observed = False
    aggregate_assets: dict[str, int] = {}
    aggregate_liabilities: dict[str, int] = {}
    for address, changes in asset_deltas.items():
        if address.lower() not in victims:
            continue
        for asset, raw_delta in changes.items():
            try:
                delta = int(raw_delta)
            except (TypeError, ValueError):
                return HarmAssessment(HarmStatus.UNKNOWN, None, "invalid raw asset delta")
            # An explicit zero is an observed balance, not missing coverage.
            # Only an absent owner/asset entry is unobserved.
            observed = True
            if delta == 0:
                continue
            aggregate_assets[asset.lower()] = aggregate_assets.get(asset.lower(), 0) + delta
        if specification.measure == "net_asset_loss":
            owner_liabilities = _owner_changes(liability_data, address.lower()) or {}
            for asset, raw_delta in owner_liabilities.items():
                try:
                    liability_delta = int(raw_delta)
                except (TypeError, ValueError):
                    return HarmAssessment(HarmStatus.UNKNOWN, None, "invalid liability delta")
                aggregate_liabilities[asset.lower()] = aggregate_liabilities.get(asset.lower(), 0) + liability_delta
    for asset, delta in aggregate_assets.items():
        metadata = specification.assets.get(asset)
        if metadata is None:
            return HarmAssessment(HarmStatus.UNKNOWN, None, f"missing price metadata for {asset}")
        try:
            decimals, raw_price = metadata
            price = Decimal(str(raw_price))
        except (TypeError, ValueError, InvalidOperation):
            return HarmAssessment(HarmStatus.UNKNOWN, None, f"invalid valuation metadata for {asset}")
        if not isinstance(decimals, int) or not 0 <= decimals <= 255 or price < 0 or not price.is_finite():
            return HarmAssessment(HarmStatus.UNKNOWN, None, f"invalid valuation metadata for {asset}")
        total_loss -= (Decimal(delta) / (Decimal(10) ** decimals)) * price
    if specification.measure == "net_asset_loss":
        for asset, liability_delta in aggregate_liabilities.items():
            if not liability_delta:
                continue
            metadata = specification.assets.get(asset)
            if metadata is None:
                return HarmAssessment(HarmStatus.UNKNOWN, None, f"missing liability price metadata for {asset}")
            try:
                decimals, raw_price = metadata
                price = Decimal(str(raw_price))
            except (TypeError, ValueError, InvalidOperation):
                return HarmAssessment(HarmStatus.UNKNOWN, None, f"invalid liability valuation metadata for {asset}")
            if not isinstance(decimals, int) or not 0 <= decimals <= 255 or price < 0 or not price.is_finite():
                return HarmAssessment(HarmStatus.UNKNOWN, None, f"invalid liability valuation metadata for {asset}")
            total_loss += (Decimal(liability_delta) / (Decimal(10) ** decimals)) * price
    if not observed:
        return HarmAssessment(HarmStatus.UNKNOWN, None, "no non-zero protected change observed")
    loss = max(Decimal("0"), total_loss)
    status = HarmStatus.HARM if loss > specification.threshold else HarmStatus.NO_HARM
    return HarmAssessment(status, loss, f"{specification.measure}; threshold={specification.threshold}")
