"""Simulated block builder: greedy bundle auction per slot, optional filter, then loose mempool txs.

Filter modes:
  none         include every valid bundle (today's builder)
  heur_strict  exclude bundles matching the mev-inspect-style sandwich shape
  heur_naive   exclude every front-victim-back shape
  l1_only      exclude everything layer 1 flags
  tg_open      layer 1 then layer 2; DEFAULT (INCONCLUSIVE) -> include (fail-open)
  tg_closed    layer 1 then layer 2; DEFAULT (INCONCLUSIVE) -> exclude (fail-closed)
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field

from .agents import Bundle, SimTx
from .amm import AmmModel, victim_harm
from .chain import Receipt, World
from .detection import (EXCLUDE, INCLUDE, Thresholds, decide, heuristic_naive, heuristic_strict, layer1,
                        layer2, resolve)

MODES = ("none", "heur_strict", "heur_naive", "l1_only", "tg_open", "tg_closed")


@dataclass
class BundleRecord:
    slot: int
    bid_id: str
    kind: str
    variant: str
    attack: bool
    bid: float
    status: str = ""               # included | excluded | invalid | conflict
    l1_flagged: bool | None = None
    l1_same_direction: bool | None = None
    strict: bool | None = None
    naive: bool | None = None
    verdict: str | None = None
    reason: str | None = None
    harm_l2: int | None = None
    confounded: list[int] = field(default_factory=list)
    confound_kind: str = ""
    decision: str | None = None    # layer-2 policy output: INCLUDE | EXCLUDE | DEFAULT
    gt_harm: int | None = None     # x*y=k ground truth, victim output token units
    gt_harm_a: float | None = None # same, in token-A units at the pre-bundle mid price
    sim_ms: float = 0.0
    l1_ms: float = 0.0
    l2_ms: float = 0.0


@dataclass
class SlotRecord:
    slot: int
    n_users: int
    n_bundles: int
    users_included_ok: int
    users_reverted: int
    l1_ms: float
    l2_ms: float
    heuristic_ms: float
    build_ms: float
    bundles: list[BundleRecord]


class Builder:
    def __init__(self, world: World, mode: str, thr: Thresholds | None = None):
        assert mode in MODES, mode
        self.w, self.mode, self.thr = world, mode, thr or Thresholds()
        self.rpc = world.rpc
        self.pools = {p.lower() for p in world.pools.values()}
        self.pool_tokens = world.pool_tokens

    def _exec(self, txs: list[SimTx]) -> list[Receipt]:
        return [self.rpc.send(t.sender, t.to, t.data) for t in txs]

    def model(self) -> AmmModel:
        return AmmModel(self.pool_tokens, self.w.reserves())

    def build_slot(self, slot: int, users: list[SimTx], bundles: list[Bundle], price_a) -> SlotRecord:
        t_slot = time.perf_counter()
        included: set[str] = set()
        records: list[BundleRecord] = []
        l1_total = l2_total = heur_total = 0.0
        for b in sorted(bundles, key=lambda b: (-b.bid, b.bid_id)):
            rec = BundleRecord(slot, b.bid_id, b.kind, b.variant, b.attack, b.bid)
            records.append(rec)
            if any(t.tid in included for t in b.txs):
                rec.status = "conflict"
                continue
            pre_model = self.model() if b.attack else None
            snap = self.rpc.snapshot()
            t0 = time.perf_counter()
            obs = self._exec(b.txs)
            rec.sim_ms = (time.perf_counter() - t0) * 1e3
            if any(r.status != 1 for r in obs):
                self.rpc.revert(snap)
                rec.status = "invalid"
                continue
            public = [t.public for t in b.txs]
            senders = [t.sender.lower() for t in b.txs]
            vi = public.index(True)
            if b.attack:  # x*y=k ground truth on the pre-bundle reserves, independent of the EVM
                pre_ops = [t.op for t in b.txs[:vi] if t.op is not None]
                victim = b.txs[vi]
                rec.gt_harm = victim_harm(pre_model, pre_ops, victim.op)
                tout = pre_model.token_out(victim.op.pools, victim.op.token_in)
                rec.gt_harm_a = rec.gt_harm / 1e18 * price_a(tout, pre_model)

            t0 = time.perf_counter()
            rec.strict = heuristic_strict(obs, senders, public, vi, self.pools)
            rec.naive = heuristic_naive(obs, senders, public, vi, self.pools)
            heur_ms = (time.perf_counter() - t0) * 1e3
            t0 = time.perf_counter()
            l1 = layer1(obs, public, vi, self.pools)
            rec.l1_ms = (time.perf_counter() - t0) * 1e3
            rec.l1_flagged, rec.l1_same_direction = l1.flagged, l1.same_direction
            if self.mode in ("heur_strict", "heur_naive"):
                heur_total += heur_ms

            decision = INCLUDE
            if self.mode == "heur_strict" and rec.strict:
                decision = EXCLUDE
            elif self.mode == "heur_naive" and rec.naive:
                decision = EXCLUDE
            elif self.mode == "l1_only" and l1.flagged:
                decision = EXCLUDE
            elif self.mode in ("tg_open", "tg_closed") and l1.flagged:
                l1_total += rec.l1_ms
                self.rpc.revert(snap)          # back to the block prefix before this bundle

                def run_cf(keep: list[int]) -> list[Receipt]:
                    s = self.rpc.snapshot()
                    out = self._exec([b.txs[k] for k in keep])
                    self.rpc.revert(s)
                    return out

                t0 = time.perf_counter()
                v = layer2(obs, run_cf, b.txs[vi].sender, vi, l1.suspects, self.pools, self.thr)
                rec.l2_ms = (time.perf_counter() - t0) * 1e3
                l2_total += rec.l2_ms
                rec.verdict, rec.reason, rec.harm_l2, rec.confounded = v.verdict, v.reason, v.harm, v.confounded
                rec.confound_kind, rec.decision = v.confound_kind, decide(v.verdict)
                decision = resolve(rec.decision, INCLUDE if self.mode == "tg_open" else EXCLUDE)
                snap = self.rpc.snapshot()
                if decision == INCLUDE:        # re-apply the observed bundle on the prefix
                    again = self._exec(b.txs)
                    assert [r.status for r in again] == [1] * len(again)
            elif self.mode in ("tg_open", "tg_closed"):
                l1_total += rec.l1_ms

            if decision == EXCLUDE:
                self.rpc.revert(snap)
                rec.status = "excluded"
                continue
            rec.status = "included"
            included.update(t.tid for t in b.txs)

        ok = reverted = 0
        for u in users:
            if u.tid in included:
                ok += 1
                continue
            r = self._exec([u])[0]
            ok += r.status == 1
            reverted += r.status != 1
        return SlotRecord(slot, len(users), len(bundles), ok, reverted, l1_total, l2_total, heur_total,
                          (time.perf_counter() - t_slot) * 1e3, records)


def as_dict(rec: SlotRecord) -> dict:
    return asdict(rec)
