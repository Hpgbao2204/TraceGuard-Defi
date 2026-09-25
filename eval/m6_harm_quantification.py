"""Optional USD severity layer; never changes raw harm status."""
from decimal import Decimal
from eval.m6_harm_v2 import REGISTRY

DECIMALS = {a["symbol"].lower(): int(a["decimals"]) for a in REGISTRY["assets"]}
DECIMALS_BY_ADDRESS = {a["address"].lower(): int(a["decimals"]) for a in REGISTRY["assets"] if a.get("address")}

def quantify(hard_deltas: dict[str, str], prices_usd: dict[str, str] | None):
    if not prices_usd:
        return {"status": "QUANTIFICATION_UNAVAILABLE", "usd": None}
    total = Decimal("0")
    missing = []
    for asset, raw in hard_deltas.items():
        key = asset.lower()
        price_key = asset if asset in prices_usd else asset.upper()
        if price_key not in prices_usd:
            missing.append(asset); continue
        decimals = DECIMALS_BY_ADDRESS.get(key, DECIMALS.get(key, 18))
        total += Decimal(raw) / (Decimal(10) ** decimals) * Decimal(str(prices_usd[price_key]))
    if missing:
        return {"status": "QUANTIFICATION_PARTIAL", "usd": str(total), "missing_prices": sorted(set(missing))}
    return {"status": "QUANTIFIED", "usd": str(total)}
