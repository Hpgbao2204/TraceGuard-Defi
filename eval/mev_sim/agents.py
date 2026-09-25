"""Seeded mempool: ordinary users, benign searchers and sandwich bots (including adaptive ones).

Each slot, users post swaps to the public mempool. Searchers read them and send bundles
(ordered transaction lists that embed the user's transaction) to the builder. Every bundle carries
its ground-truth label because we generate it. Sizes are computed on the AMM model of the chain at
slot start, so bundles can go stale when other bundles land first, as they would in practice.

User arrivals, routes, sizes and every searcher decision are drawn from ``Random(f"{seed}:{slot}")``
and do not depend on chain state, so all builder configurations face the same order flow.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from .amm import AmmModel, SwapOp
from .chain import TAG_FRESH, World, addr, calldata

SANDWICH_VARIANTS = ("classic", "split", "addr_swap", "aggregator", "decoy")
LOOKALIKE_KINDS = ("jit", "mm_reverse", "xpool")


@dataclass
class FlowConfig:
    users_per_slot: float = 4.0
    p_sandwich: float = 0.45       # chance a sandwich bot targets a given user swap
    p_lookalike: float = 0.30      # chance a benign shape-lookalike searcher targets it instead
    bid_share: float = 0.8         # share of expected profit a searcher bids to the builder
    min_arb_profit_a: float = 0.001


@dataclass
class SimTx:
    tid: str
    sender: str
    to: str
    data: str
    role: str                      # user | front | back | decoy | arb | jit_add | jit_remove | pre | post
    op: SwapOp | None = None       # effect in the AMM model (swaps only), for ground truth
    public: bool = False           # a public-mempool user transaction


@dataclass
class Bundle:
    bid_id: str
    kind: str                      # sandwich | arb_backrun | jit | mm_reverse | xpool
    variant: str
    attack: bool
    txs: list[SimTx]
    victim: str                    # tid of the embedded user transaction
    bid: float                     # in token-A units
    expected_profit: float = 0.0
    meta: dict = field(default_factory=dict)


def router_swap(w: World, amount_in: int, min_out: int, pools, token_in: str, to: str) -> str:
    return calldata("swapExactIn(uint256,uint256,address[],address,address)",
                    amount_in, min_out, list(pools), token_in, to)


def agg_swap(routes: list[tuple[int, tuple[str, ...]]], token_in: str, min_out: int, to: str) -> str:
    return calldata("multiSwap((uint256,address[])[],address,uint256,address)",
                    [(a, list(p)) for a, p in routes], token_in, min_out, to)


def _poisson(rng: random.Random, lam: float) -> int:
    n, t = 0, rng.expovariate(1.0)
    while t < lam:
        n += 1
        t += rng.expovariate(1.0)
    return n


def _argmax_int(f, lo: int, hi: int) -> int:
    """Ternary search for the maximiser of a unimodal integer function."""
    while hi - lo >= 3:
        m1 = lo + (hi - lo) // 3
        m2 = hi - (hi - lo) // 3
        if f(m1) < f(m2):
            lo = m1
        else:
            hi = m2
    return max(range(lo, hi + 1), key=f)


class OrderFlow:
    def __init__(self, world: World, seed: int, cfg: FlowConfig | None = None):
        self.w = world
        self.seed = seed
        self.cfg = cfg or FlowConfig()
        P1, P2, P3 = (world.pools[k] for k in ("P1", "P2", "P3"))
        A, B, C = (world.tokens[k] for k in "ABC")
        self.P1, self.P2, self.P3, self.A, self.B, self.C = P1, P2, P3, A, B, C
        self.price_route = {B: [P1], C: [P3, P1]}

    # ---------------------------------------------------------------- users
    def users(self, rng: random.Random, slot: int, model: AmmModel) -> list[SimTx]:
        out = []
        for k in range(_poisson(rng, self.cfg.users_per_slot)):
            sender = rng.choice(self.w.users)
            r = rng.random()
            if r < 0.55:
                pools, tin = (self.P1,), rng.choice([self.A, self.B])
            elif r < 0.70:
                pools, tin = (self.P2,), rng.choice([self.A, self.B])
            elif rng.random() < 0.5:
                pools, tin = (self.P1, self.P3), self.A
            else:
                pools, tin = (self.P3, self.P1), self.C
            t0, _ = model.pool_tokens[pools[0]]
            r_in = model.reserves[pools[0]][0 if tin == t0 else 1]
            amount = int(r_in * rng.uniform(0.002, 0.02))
            slippage = rng.choice([0.005, 0.01, 0.02, 0.03])
            min_out = int(model.quote(pools, tin, amount) * (1 - slippage))
            via_agg = rng.random() < 0.2
            data = (agg_swap([(amount, pools)], tin, min_out, sender) if via_agg
                    else router_swap(self.w, amount, min_out, pools, tin, sender))
            tx = SimTx(f"s{slot}u{k}", sender, self.w.aggregator if via_agg else self.w.router, data,
                       "user", SwapOp(pools, tin, amount), public=True)
            tx.min_out = min_out  # type: ignore[attr-defined]
            out.append(tx)
        return out

    # ---------------------------------------------------------------- bundles
    def slot(self, slot: int, model: AmmModel) -> tuple[list[SimTx], list[Bundle]]:
        rng = random.Random(f"{self.seed}:{slot}")
        users = self.users(rng, slot, model)
        bundles: list[Bundle] = []
        for v in users:
            u = rng.random()
            choice = rng.random()
            searchers = rng.sample(self.w.searchers, 2)
            fresh = addr(slot * 1000 + int(v.tid.split("u")[1]), TAG_FRESH)
            arb = self._arb(v, model, rng.choice(self.w.searchers))
            if arb:
                bundles.append(arb)
            if u < self.cfg.p_sandwich:
                variant = ("multipool" if len(v.op.pools) > 1
                           else SANDWICH_VARIANTS[int(choice * len(SANDWICH_VARIANTS))])
                sw = self._sandwich(v, model, variant, searchers, fresh, rng)
                if sw:
                    bundles.append(sw)
            elif u < self.cfg.p_sandwich + self.cfg.p_lookalike and v.op.pools == (self.P1,):
                kind = LOOKALIKE_KINDS[int(choice * len(LOOKALIKE_KINDS))]
                bundles.append(self._lookalike(v, model, kind, searchers[0], rng, arb))
        return users, bundles

    def _value_a(self, token: str, amount: int, model: AmmModel) -> float:
        return amount / 1e18 * model.price_in(token, self.A, self.price_route)

    def _sandwich(self, v: SimTx, model: AmmModel, variant: str, searchers, fresh, rng) -> Bundle | None:
        pools, tin = v.op.pools, v.op.token_in
        rev = tuple(reversed(pools))
        tout = model.token_out(pools, tin)
        min_out = v.min_out  # type: ignore[attr-defined]
        t0, _ = model.pool_tokens[pools[0]]
        r_in = model.reserves[pools[0]][0 if tin == t0 else 1]

        def victim_ok(f: int) -> bool:
            m = model.copy()
            m.swap(SwapOp(pools, tin, f))
            return m.swap(v.op) >= min_out

        lo, hi = 0, r_in // 2
        if not victim_ok(1):
            return None
        while hi - lo > 1:  # largest front the victim's slippage limit tolerates
            mid = (lo + hi) // 2
            lo, hi = (mid, hi) if victim_ok(mid) else (lo, mid)
        fmax = lo * 97 // 100

        def profit(f: int) -> int:
            m = model.copy()
            got = m.swap(SwapOp(pools, tin, f))
            m.swap(v.op)
            return m.swap(SwapOp(rev, tout, got)) - f

        f = _argmax_int(profit, 0, fmax)
        if f <= 0 or profit(f) <= 0:
            return None
        e1, e2 = searchers
        w = self.w
        fronts: list[tuple[int, str]] = []  # (amount, sender)
        if variant == "split":
            k = rng.randint(2, 4)
            fronts = [(f // k + (f % k if i == k - 1 else 0), e1) for i in range(k)]
        else:
            fronts = [(f, e1)]
        m = model.copy()
        outs = [m.swap(SwapOp(pools, tin, a)) for a, _ in fronts]
        got = sum(outs)
        m.swap(v.op)
        back_out = m.swap(SwapOp(rev, tout, got))
        gain = back_out - f
        if gain <= 0:
            return None
        front_to = {"addr_swap": e2, "decoy": fresh}.get(variant, e1)
        back_from = e2 if variant in ("addr_swap", "decoy") else e1
        txs: list[SimTx] = []
        for i, (a, s) in enumerate(fronts):
            data = (agg_swap([(a, pools)], tin, 0, front_to) if variant == "aggregator"
                    else router_swap(w, a, 0, pools, tin, front_to))
            to = w.aggregator if variant == "aggregator" else w.router
            txs.append(SimTx(f"{v.tid}f{i}", s, to, data, "front", SwapOp(pools, tin, a)))
        if variant == "decoy":  # proceeds hop through a fresh account: reverts if the front-run is dropped
            txs.append(SimTx(f"{v.tid}d", fresh, tout, calldata("transfer(address,uint256)", e2, got), "decoy"))
        txs.append(v)
        back_data = (agg_swap([(got, rev)], tout, f, back_from) if variant == "aggregator"
                     else router_swap(w, got, f, rev, tout, back_from))
        txs.append(SimTx(f"{v.tid}b", back_from, w.aggregator if variant == "aggregator" else w.router,
                         back_data, "back", SwapOp(rev, tout, got)))
        profit_a = self._value_a(tin, gain, model)
        return Bundle(f"{v.tid}:sandwich", "sandwich", variant, True, txs, v.tid,
                      self.cfg.bid_share * profit_a, profit_a, {"front": f, "n_fronts": len(fronts)})

    def _arb(self, v: SimTx, model: AmmModel, searcher: str) -> Bundle | None:
        if not ({self.P1, self.P2} & set(v.op.pools)):
            return None
        after = model.copy()
        after.swap(v.op)
        best = None
        for path in ((self.P1, self.P2), (self.P2, self.P1)):
            r_a = after.reserves[path[0]][0 if after.pool_tokens[path[0]][0] == self.A else 1]
            x = _argmax_int(lambda a: after.quote(path, self.A, a) - a, 0, r_a // 5)
            gain = after.quote(path, self.A, x) - x
            if best is None or gain > best[2]:
                best = (path, x, gain)
        path, x, gain = best
        if gain / 1e18 < self.cfg.min_arb_profit_a:
            return None
        tx = SimTx(f"{v.tid}a", searcher, self.w.router, router_swap(self.w, x, x, path, self.A, searcher),
                   "arb", SwapOp(path, self.A, x))
        profit_a = gain / 1e18
        return Bundle(f"{v.tid}:arb", "arb_backrun", "arb_backrun", False, [v, tx], v.tid,
                      self.cfg.bid_share * profit_a * 0.5, profit_a)

    def _lookalike(self, v: SimTx, model: AmmModel, kind: str, s: str, rng, arb: Bundle | None) -> Bundle:
        w, P1, P2 = self.w, self.P1, self.P2
        tin = v.op.token_in
        tout = model.token_out(v.op.pools, tin)
        # Lookalike strategies bid just above the backrun so the builder evaluates them; this
        # measures false-positive decisions, not the economics of these strategies.
        bid = (arb.bid * 1.1 if arb else 0.0) + 1e-4
        if kind == "jit":
            r0, r1 = model.reserves[P1]
            share = rng.uniform(0.5, 2.0)
            pre = SimTx(f"{v.tid}j0", s, w.router, calldata("addLiquidity(address,uint256,uint256,address)",
                                                              P1, int(r0 * share), int(r1 * share), s), "jit_add")
            post = SimTx(f"{v.tid}j1", s, w.router, calldata("removeAll(address,address)", P1, s), "jit_remove")
        else:
            pool = P1 if kind == "mm_reverse" else P2
            t_pre = tout if kind == "mm_reverse" else tin
            t0, _ = model.pool_tokens[pool]
            size = int(model.reserves[pool][0 if t_pre == t0 else 1] * rng.uniform(0.001, 0.01))
            got = model.quote((pool,), t_pre, size)
            t_post = model.token_out((pool,), t_pre)
            pre = SimTx(f"{v.tid}m0", s, w.router, router_swap(w, size, 0, (pool,), t_pre, s), "pre",
                        SwapOp((pool,), t_pre, size))
            post = SimTx(f"{v.tid}m1", s, w.router, router_swap(w, got, 0, (pool,), t_post, s), "post",
                         SwapOp((pool,), t_post, got))
        return Bundle(f"{v.tid}:{kind}", kind, kind, False, [pre, v, post], v.tid, bid)
