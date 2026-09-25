"""Deterministic on-chain-only prices from the preregistered manifest."""

from __future__ import annotations

import json
import math
from pathlib import Path

from core.rpc import RpcClient


OBSERVE_SELECTOR = "883bdbfd"
TOKEN0_SELECTOR = "0dfe1681"
TOKEN1_SELECTOR = "d21220a7"


def load_price_manifest(path: str | Path) -> dict:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("status") != "preregistered" or payload.get("policy") != "on-chain-only-two-tier":
        raise ValueError("price manifest is not the preregistered on-chain policy")
    return payload


def _word(value: int) -> str:
    return format(value, "064x")


def _signed_word(word: str) -> int:
    value = int(word, 16)
    return value - (1 << 256) if value >= (1 << 255) else value


def _observe_twap_tick(archive: RpcClient, pool: str, block: int, window: int) -> int:
    # observe(uint32[2]) ABI: dynamic-array offset, length, secondsAgos.
    data = "0x" + OBSERVE_SELECTOR + _word(32) + _word(2) + _word(window) + _word(0)
    result = archive.call("eth_call", [{"to": pool, "data": data}, hex(block)])
    raw = str(result or "").removeprefix("0x")
    if len(raw) < 64:
        raise ValueError(f"Uniswap V3 observe returned short data for {pool}")
    first_offset = int(raw[0:64], 16) * 2
    if first_offset % 64 or first_offset + 192 > len(raw):
        raise ValueError("invalid observe int56 array offset")
    length = int(raw[first_offset:first_offset + 64], 16)
    if length != 2:
        raise ValueError(f"expected two tick cumulatives, got {length}")
    a = _signed_word(raw[first_offset + 64:first_offset + 128])
    b = _signed_word(raw[first_offset + 128:first_offset + 192])
    # Solidity integer division floors for negative values; Python // matches it.
    return (b - a) // window


def _pool_token(archive: RpcClient, pool: str, block: int, selector: str) -> str:
    """Read and validate a V3 pool token address at the reference block."""
    result = archive.call(
        "eth_call", [{"to": pool, "data": "0x" + selector}, hex(block)])
    raw = str(result or "")
    if not raw.startswith("0x") or len(raw) != 66:
        raise ValueError(f"pool token() returned invalid ABI data for {pool}")
    return "0x" + raw[-40:].lower()


def _tick_price(tick: int, token0_decimals: int, token1_decimals: int,
                target_is_token0: bool) -> float:
    raw_token1_per_token0 = 1.0001 ** tick
    human_token1_per_token0 = raw_token1_per_token0 * 10 ** (token0_decimals - token1_decimals)
    return human_token1_per_token0 if target_is_token0 else 1.0 / human_token1_per_token0


def validate_price_provenance(
    prices: dict[str, dict[str, float | int]], *, reference_block: int,
    target_block: int | None = None,
) -> None:
    """Validate the provenance contract for every resolved asset price."""
    if not isinstance(reference_block, int) or reference_block < 0:
        raise ValueError("price reference block must be non-negative")
    if target_block is not None and (
            not isinstance(target_block, int) or target_block <= reference_block):
        raise ValueError("price reference must precede target block")
    for asset, record in prices.items():
        if not isinstance(record, dict):
            raise ValueError(f"price record is not an object for {asset}")
        if record.get("reference_block") != reference_block:
            raise ValueError(f"price reference block mismatch for {asset}")
        source = record.get("source")
        if not isinstance(source, str) or not source:
            raise ValueError(f"price provenance source missing for {asset}")
        try:
            price = float(record["usd_per_token"])
            decimals = int(record["decimals"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid price metadata for {asset}") from exc
        if not math.isfinite(price) or price < 0 or not 0 <= decimals <= 255:
            raise ValueError(f"invalid price metadata for {asset}")


def resolve_reference_prices(archive: RpcClient, manifest: dict, block: int) -> dict[str, dict[str, float | int]]:
    """Resolve reference token USD prices at ``block`` (normally target-1)."""
    if not isinstance(block, int) or block < 0:
        raise ValueError("reference price block must be a non-negative integer")
    assets = manifest["reference_assets"]
    prices: dict[str, dict[str, float | int]] = {}
    for symbol, spec in assets.items():
        if spec["pricing"] == "fixed_usd_1":
            prices[spec["address"].lower()] = {
                "usd_per_token": 1.0, "decimals": int(spec["decimals"]),
                "reference_block": block,
                "source": "preregistered:fixed_usd_1",
            }
    usdc = assets["USDC"]
    for symbol in ("WETH", "WBTC"):
        spec = assets[symbol]
        pool = str(spec["reference_pool"]).lower()
        token0 = _pool_token(archive, pool, block, TOKEN0_SELECTOR)
        token1 = _pool_token(archive, pool, block, TOKEN1_SELECTOR)
        target = str(spec["address"]).lower()
        quote = str(usdc["address"]).lower()
        if {token0, token1} != {target, quote}:
            raise ValueError(
                f"reference pool {pool} does not contain {symbol}/USDC")
        tick = _observe_twap_tick(archive, pool, block,
                                  int(spec["twap_window_seconds"]))
        token_price = _tick_price(
            tick,
            int(spec["decimals"]) if target == token0 else int(usdc["decimals"]),
            int(usdc["decimals"]) if target == token0 else int(spec["decimals"]),
            target == token0,
        )
        prices[spec["address"].lower()] = {
            "usd_per_token": token_price, "decimals": int(spec["decimals"]),
            "reference_block": block,
            "source": (f"eth_call:uniswap_v3_observe:{spec['reference_pool']}"
                       f":window={int(spec['twap_window_seconds'])}"),
        }
    validate_price_provenance(prices, reference_block=block)
    return prices


def harm_spec_from_manifest(archive: RpcClient, manifest: dict, block: int,
                            attacker: str | None = None,
                            *, target_block: int | None = None) -> dict:
    prices = resolve_reference_prices(archive, manifest, block)
    validate_price_provenance(
        prices, reference_block=block, target_block=target_block)
    return {
        "oracle": "attacker_value_delta",
        "attacker": attacker or "",
        "token_prices": prices,
        "native_price_usd": prices[manifest["reference_assets"]["WETH"]["address"].lower()]["usd_per_token"],
        "lmin_usd": float(manifest["lmin_usd"]),
        "valuation_source": "eval/e4_price_manifest.json:onchain_uniswap_v3_twap",
        "price_reference_block": block,
        "target_block": target_block,
        "price_provenance": {
            asset: {"reference_block": record["reference_block"],
                    "source": record["source"]}
            for asset, record in prices.items()
        },
    }


def bind_price_provenance(
    spec: dict, prices: dict[str, dict[str, float | int]],
    *, field_to_asset: dict[str, str], reference_block: int,
    target_block: int,
) -> dict:
    """Bind resolved historical price records to named harm-spec fields."""
    validate_price_provenance(
        prices, reference_block=reference_block, target_block=target_block)
    bound = dict(spec)
    provenance: dict[str, dict[str, int | str]] = {}
    for field, asset in field_to_asset.items():
        record = prices.get(str(asset).lower())
        if record is None:
            raise ValueError(f"resolved historical price missing for {asset}")
        bound[field] = record["usd_per_token"]
        provenance[field] = {
            "reference_block": record["reference_block"],
            "source": record["source"],
        }
    bound["price_reference_block"] = reference_block
    bound["target_block"] = target_block
    bound["price_provenance"] = provenance
    return bound


def pool_harm_spec_from_manifest(
    archive: RpcClient, manifest: dict, reference_block: int,
    protected_owner: str, *, target_block: int, protected_asset: str = "native eth",
    protected_token: str | None = None,
) -> dict:
    """Build a provenance-bound native/WETH pool harm specification."""
    prices = resolve_reference_prices(archive, manifest, reference_block)
    weth = manifest["reference_assets"]["WETH"]["address"].lower()
    spec = {
        "oracle": "pool_balance_delta",
        "protected_owner": protected_owner,
        "protected_asset": protected_asset,
        "protected_token": protected_token or weth,
        "lmin_usd": float(manifest["lmin_usd"]),
        "valuation_source": "eval/e4_price_manifest.json:onchain_uniswap_v3_twap",
    }
    bound = bind_price_provenance(
        spec, prices, field_to_asset={"native_price_usd": weth},
        reference_block=reference_block, target_block=target_block)
    return bound


def euler_harm_spec_from_manifest(
    archive: RpcClient, manifest: dict, reference_block: int,
    *, target_block: int, violator: str, debt_token: str,
    collateral_token: str, collateral_underlying_per_token: float,
    liquidation_event_address: str, lmin_usd: float | None = None,
    collateral_rate_reference_block: int | None = None,
    collateral_rate_source: str = "",
) -> dict:
    """Build an Euler bad-debt spec from two resolver-covered assets.

    Asset-specific cases must be added to the preregistered manifest before
    this factory can produce a release-eligible specification. Unknown assets
    fail rather than falling back to a guessed USD price.
    """
    prices = resolve_reference_prices(archive, manifest, reference_block)
    debt_key = str(debt_token).lower()
    collateral_key = str(collateral_token).lower()
    debt_record = prices.get(debt_key)
    collateral_record = prices.get(collateral_key)
    if debt_record is None or collateral_record is None:
        missing = debt_key if debt_record is None else collateral_key
        raise ValueError(f"resolved historical price missing for {missing}")
    spec = {
        "oracle": "euler_bad_debt_delta",
        "violator": violator,
        "debt_token": debt_token,
        "collateral_token": collateral_token,
        "debt_decimals": debt_record["decimals"],
        "collateral_decimals": collateral_record["decimals"],
        "collateral_underlying_per_token": collateral_underlying_per_token,
        "collateral_rate_provenance": {
            "reference_block": collateral_rate_reference_block,
            "source": collateral_rate_source,
        },
        "liquidation_event_address": liquidation_event_address,
        "lmin_usd": (float(manifest["lmin_usd"])
                      if lmin_usd is None else lmin_usd),
        "valuation_source": "eval/e4_price_manifest.json:historical_resolver",
    }
    return bind_price_provenance(
        spec, prices,
        field_to_asset={"debt_price_usd": debt_key,
                        "collateral_price_usd": collateral_key},
        reference_block=reference_block, target_block=target_block)
