"""Typed raw hard-asset harm engine for M6 Harm-v2.

USD valuation is deliberately absent from the primary predicate. T0 uses the
attacker complement; T1 uses an explicit frozen protected registry.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = json.loads((ROOT / "eval/e4/hard_assets_v1.json").read_text())
HARD = {a["address"].lower(): a for a in REGISTRY["assets"] if a.get("address")}
HARD_SYMBOLS = {a["symbol"].lower() for a in REGISTRY["assets"]}
ZERO = "0x" + "0" * 40
SPEC = "harm-spec-v2|raw-hard-assets|v1"

@dataclass(frozen=True)
class HarmObservation:
    status: str
    tier: str
    detection_spec_id: str
    hard_asset_registry: str
    boundary_id: str
    hard_deltas: dict[str, int]
    exotic_deltas: dict[str, int]
    observed_addresses: tuple[str, ...]
    attacker_addresses: tuple[str, ...]
    protected_addresses: tuple[str, ...]
    reason_code: str | None = None

    def json(self):
        x = asdict(self)
        x["hard_deltas"] = {k: str(v) for k, v in x["hard_deltas"].items()}
        x["exotic_deltas"] = {k: str(v) for k, v in x["exotic_deltas"].items()}
        x["observed_addresses"] = list(self.observed_addresses)
        x["attacker_addresses"] = list(self.attacker_addresses)
        x["protected_addresses"] = list(self.protected_addresses)
        return x

def normalize_flows(flows, native_flows=()):
    out = list(flows or [])
    for f in native_flows or []:
        out.append({"token": "eth", "from": f["from"], "to": f["to"], "amount_raw": f["amount_raw"]})
    return out

def _engine(flows, attackers, protected, tier, boundary_id, complete=True):
    if not complete:
        return HarmObservation("UNKNOWN", tier, SPEC, REGISTRY["version"], boundary_id, {}, {}, tuple(), tuple(sorted(attackers)), tuple(sorted(protected)), "RAW_OBSERVATION_INCOMPLETE")
    observed = set(); hard = {}; exotic = {}
    for f in flows:
        try:
            src, dst, token = f["from"].lower(), f["to"].lower(), f["token"].lower()
            amount = int(f["amount_raw"])
        except (KeyError, TypeError, ValueError):
            return HarmObservation("UNKNOWN", tier, SPEC, REGISTRY["version"], boundary_id, {}, {}, tuple(), tuple(sorted(attackers)), tuple(sorted(protected)), "MALFORMED_RAW_FLOW")
        observed.update((src, dst))
        if token in HARD or token in {"eth", "weth", "usdc", "usdt", "dai", "wbtc"}:
            hard.setdefault(token, {})
            if dst in protected: hard[token][dst] = hard[token].get(dst, 0) + amount
            if src in protected: hard[token][src] = hard[token].get(src, 0) - amount
        else:
            exotic.setdefault(token, {})
            if dst in protected: exotic[token][dst] = exotic[token].get(dst, 0) + amount
            if src in protected: exotic[token][src] = exotic[token].get(src, 0) - amount
    hard_total = {t: sum(v.values()) for t, v in hard.items()}
    exotic_total = {t: sum(v.values()) for t, v in exotic.items()}
    if not hard_total:
        return HarmObservation("UNKNOWN", tier, SPEC, REGISTRY["version"], boundary_id, {}, exotic_total,
                               tuple(sorted(observed - {ZERO})), tuple(sorted(attackers)),
                               tuple(sorted(protected - {ZERO})), "T0_NO_OBSERVABLE_HARD_ASSET_FLOW")
    status = "HARM" if any(v < 0 for v in hard_total.values()) else "NO_HARM"
    return HarmObservation(status, tier, SPEC, REGISTRY["version"], boundary_id, hard_total, exotic_total,
                           tuple(sorted(observed - {ZERO})), tuple(sorted(attackers)), tuple(sorted(protected - {ZERO})))

def t0(flows, sender, created_contracts=(), complete=True, infrastructure=()):
    if not sender:
        return HarmObservation("UNKNOWN", "T0", SPEC, REGISTRY["version"], "auto-complement-v1", {}, {}, tuple(), tuple(), tuple(), "ATTACKER_SEED_MISSING")
    attackers = {sender.lower(), *(str(x).lower() for x in created_contracts)} - {ZERO}
    touched = {str(f.get(k, "")).lower() for f in flows for k in ("from", "to") if f.get(k)} - {ZERO} - {str(x).lower() for x in infrastructure}
    return _engine(flows, attackers, touched - attackers, "T0", "auto-complement-v1", complete)

def t1(flows, protected_addresses, attacker_addresses=(), boundary_id="frozen-protected-registry-v1", complete=True):
    protected = {str(x).lower() for x in protected_addresses or ()} - {ZERO}
    if not protected:
        return HarmObservation("UNKNOWN", "T1", SPEC, REGISTRY["version"], boundary_id, {}, {}, tuple(), tuple(), tuple(), "PROTECTED_REGISTRY_MISSING")
    return _engine(flows, {str(x).lower() for x in attacker_addresses}, protected, "T1", boundary_id, complete)
