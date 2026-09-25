"""Layer 1 screener, shape-heuristic baselines, layer 2 counterfactual check and the inclusion policy.

All three read only what a builder has: the bundle's transactions, which of them came from the public
mempool, and the receipts/logs of simulating the bundle on the block being built. None of them look at
the generator's labels or at calldata, so routers, aggregators and address changes are seen only
through their effect on pool and token logs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from eth_abi import decode

from .chain import TOPIC_SWAP, TOPIC_TRANSFER, Receipt


# ------------------------------------------------------------------ log helpers
def _addr_topic(t: str) -> str:
    return "0x" + t[-40:]


def touched(rc: Receipt, pools: set[str]) -> set[str]:
    """Pools whose state the transaction changed (any log emitted by the pool)."""
    return {lg["address"].lower() for lg in rc.logs} & pools


def swaps(rc: Receipt, pools: set[str]) -> set[tuple[str, bool]]:
    """(pool, token0-in) for every Swap event of a known pool."""
    out = set()
    for lg in rc.logs:
        a = lg["address"].lower()
        if a in pools and lg["topics"][0] == TOPIC_SWAP:
            in0, in1, _, _ = decode(["uint256"] * 4, bytes.fromhex(lg["data"][2:]))
            out.add((a, in0 > 0))
    return out


def tokens_moved(rc: Receipt, pools: set[str]) -> set[str]:
    return {lg["address"].lower() for lg in rc.logs
            if lg["topics"][0] == TOPIC_TRANSFER and lg["address"].lower() not in pools}


def net_inflow(rc: Receipt, account: str, pools: set[str]) -> dict[str, int]:
    acc, out = account.lower(), {}
    for lg in rc.logs:
        tok = lg["address"].lower()
        if lg["topics"][0] != TOPIC_TRANSFER or tok in pools:
            continue
        src, dst = _addr_topic(lg["topics"][1]), _addr_topic(lg["topics"][2])
        v = int(lg["data"], 16)
        if dst == acc:
            out[tok] = out.get(tok, 0) + v
        if src == acc:
            out[tok] = out.get(tok, 0) - v
    return out


def fingerprint(rc: Receipt) -> tuple:
    return (rc.status, tuple((lg["address"].lower(), tuple(lg["topics"]), lg["data"]) for lg in rc.logs))


# ------------------------------------------------------------------ layer 1 and baselines
@dataclass
class ScreenResult:
    flagged: bool
    suspects: list[int]            # pre-victim searcher txs touching a pool the victim swaps on
    same_direction: bool


def layer1(obs: list[Receipt], public: list[bool], vi: int, pools: set[str]) -> ScreenResult:
    vpools = {p for p, _ in swaps(obs[vi], pools)}
    vswaps = swaps(obs[vi], pools)
    suspects = [i for i in range(vi) if not public[i] and touched(obs[i], vpools)]
    same_dir = any(swaps(obs[i], pools) & vswaps for i in suspects)
    return ScreenResult(bool(suspects), suspects, same_dir)


def heuristic_strict(obs, senders, public, vi, pools) -> bool:
    """mev-inspect-style: same sender swaps the victim's pool in the victim's direction before it
    and in the opposite direction after it."""
    vswaps = swaps(obs[vi], pools)
    for i in range(vi):
        if public[i]:
            continue
        pre = swaps(obs[i], pools) & vswaps
        for j in range(vi + 1, len(obs)):
            if public[j] or senders[j] != senders[i]:
                continue
            post = swaps(obs[j], pools)
            if any((p, not d) in post for p, d in pre):
                return True
    return False


def heuristic_naive(obs, senders, public, vi, pools) -> bool:
    """Block every front-victim-back shape: one sender has a tx before and after the victim and the
    one before moves a token the victim trades."""
    vtok = tokens_moved(obs[vi], pools)
    for i in range(vi):
        if public[i] or not (tokens_moved(obs[i], pools) & vtok):
            continue
        if any(not public[j] and senders[j] == senders[i] for j in range(vi + 1, len(obs))):
            return True
    return False


# ------------------------------------------------------------------ layer 2
CAUSE, NO_EFFECT, INCONCLUSIVE = "CAUSE", "NO_EFFECT", "INCONCLUSIVE"


@dataclass
class Verdict:
    verdict: str
    reason: str = ""
    harm: int | None = None         # victim output without the dropped txs minus with them
    token: str | None = None
    out_obs: int | None = None
    out_cf: int | None = None
    confounded: list[int] = field(default_factory=list)
    post_changed: list[int] = field(default_factory=list)


@dataclass
class Thresholds:
    rel: float = 0.001              # harm must be at least 10 bps of the clean output ...
    abs: int = 0                    # ... and at least this many token units


def layer2(obs: list[Receipt], run_cf: Callable[[list[int]], list[Receipt]], victim_sender: str,
           vi: int, drop: list[int], pools: set[str], thr: Thresholds) -> Verdict:
    """Drop ``drop`` (pre-victim suspects), re-simulate the rest on the same pre-state, compare."""
    inflow = net_inflow(obs[vi], victim_sender, pools)
    gained = [t for t, v in inflow.items() if v > 0]
    if len(gained) != 1:
        return Verdict(INCONCLUSIVE, "no_victim_output")
    token, out_obs = gained[0], inflow[gained[0]]
    keep = [k for k in range(len(obs)) if k not in set(drop)]
    cf_list = run_cf(keep)
    cf = dict(zip(keep, cf_list))
    if cf[vi].status != 1:
        return Verdict(INCONCLUSIVE, "victim_reverted_cf", token=token, out_obs=out_obs)
    out_cf = net_inflow(cf[vi], victim_sender, pools).get(token, 0)
    harm = out_cf - out_obs
    first = min(drop)
    confounded = [k for k in keep if first < k < vi and fingerprint(cf[k]) != fingerprint(obs[k])]
    post_changed = [k for k in keep if k > vi and cf[k].status != obs[k].status]
    v = Verdict(NO_EFFECT, "", harm, token, out_obs, out_cf, confounded, post_changed)
    if confounded:
        v.verdict, v.reason = INCONCLUSIVE, "ordering_confound"
    elif harm >= max(thr.abs, thr.rel * out_cf):
        v.verdict = CAUSE
    return v


# ------------------------------------------------------------------ policy
INCLUDE, EXCLUDE = "INCLUDE", "EXCLUDE"


def decide(verdict: str, default_on_inconclusive: str) -> str:
    if verdict == CAUSE:
        return EXCLUDE
    if verdict == NO_EFFECT:
        return INCLUDE
    return default_on_inconclusive
