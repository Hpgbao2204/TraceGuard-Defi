"""Pure-Python x*y=k model with Uniswap V2 integer math (0.3% fee).

Used by the bots to size trades and, independently of the EVM, as ground truth for victim harm.
"""
from __future__ import annotations

from dataclasses import dataclass


def amount_out(amount_in: int, r_in: int, r_out: int) -> int:
    if amount_in <= 0:
        return 0
    fee_in = amount_in * 997
    return fee_in * r_out // (r_in * 1000 + fee_in)


@dataclass
class SwapOp:
    """Exact-input swap along ``pools`` starting in ``token_in``."""
    pools: tuple[str, ...]
    token_in: str
    amount_in: int


class AmmModel:
    def __init__(self, pool_tokens: dict[str, tuple[str, str]], reserves: dict[str, tuple[int, int]]):
        self.pool_tokens = pool_tokens
        self.reserves = dict(reserves)

    def copy(self) -> "AmmModel":
        return AmmModel(self.pool_tokens, self.reserves)

    def quote(self, pools, token_in: str, amount_in: int) -> int:
        return self.copy().swap(SwapOp(tuple(pools), token_in, amount_in))

    def swap(self, op: SwapOp) -> int:
        """Apply the swap in place; return the final output amount."""
        amt, tok = op.amount_in, op.token_in
        for p in op.pools:
            t0, t1 = self.pool_tokens[p]
            r0, r1 = self.reserves[p]
            if tok == t0:
                out = amount_out(amt, r0, r1)
                self.reserves[p] = (r0 + amt, r1 - out)
                tok = t1
            elif tok == t1:
                out = amount_out(amt, r1, r0)
                self.reserves[p] = (r0 - out, r1 + amt)
                tok = t0
            else:
                raise ValueError(f"token {tok} not in pool {p}")
            amt = out
        return amt

    def token_out(self, pools, token_in: str) -> str:
        tok = token_in
        for p in pools:
            t0, t1 = self.pool_tokens[p]
            tok = t1 if tok == t0 else t0
        return tok

    def price_in(self, token: str, numeraire: str, route: dict[str, list[str]]) -> float:
        """Mid price of ``token`` in ``numeraire`` units along a fixed pool route."""
        if token == numeraire:
            return 1.0
        price, tok = 1.0, token
        for p in route[token]:
            t0, t1 = self.pool_tokens[p]
            r0, r1 = self.reserves[p]
            price *= (r1 / r0) if tok == t0 else (r0 / r1)
            tok = t1 if tok == t0 else t0
        assert tok == numeraire
        return price


def victim_harm(model: AmmModel, pre_ops: list[SwapOp], victim: SwapOp) -> int:
    """Ground-truth harm: victim output without the attacker's pre-victim swaps minus with them."""
    clean = model.copy().swap(victim)
    attacked = model.copy()
    for op in pre_ops:
        attacked.swap(op)
    return clean - attacked.swap(victim)
