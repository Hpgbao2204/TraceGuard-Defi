"""M3 end-to-end run: one command, every builder mode on the same seeded order flow.

    python -m eval.mev_sim.run --slots 200 --seed 7

Writes ``eval/mev_sim/results.json`` (git-ignored) and prints the summary table.
"""
from __future__ import annotations

import argparse
import json
import platform
import time
from dataclasses import asdict
from pathlib import Path

from .agents import FlowConfig, OrderFlow
from .builder import MODES, Builder, as_dict
from .chain import Anvil, Rpc, deploy_world
from .detection import Thresholds
from .metrics import breakdown, summarize, table

DEFAULT_OUT = Path(__file__).resolve().parent / "results.json"


def run(slots: int, seed: int, modes=MODES, thr: Thresholds | None = None, cfg: FlowConfig | None = None,
        anvil_bin: str | None = None) -> dict:
    thr, cfg = thr or Thresholds(), cfg or FlowConfig()
    raw: dict[str, list[dict]] = {}
    with Anvil(anvil_bin) as node:
        rpc = Rpc(node.url)
        world = deploy_world(rpc)
        flow = OrderFlow(world, seed, cfg)
        price_a = lambda tok, model: model.price_in(tok, world.tokens["A"], flow.price_route)  # noqa: E731
        lower = {t.lower(): t for t in world.tokens.values()}
        genesis = rpc.snapshot()
        for mode in modes:
            rpc.revert(genesis)
            genesis = rpc.snapshot()
            builder = Builder(world, mode, thr)
            recs = []
            for slot in range(slots):
                model = builder.model()
                users, bundles = flow.slot(slot, model)
                recs.append(as_dict(builder.build_slot(slot, users, bundles,
                                                       lambda tok, m: price_a(lower.get(tok.lower(), tok), m))))
            raw[mode] = recs
    harm_none = summarize(raw["none"])["victim_harm_realized_A"] if "none" in raw else None
    summary = {m: summarize(r, harm_none) for m, r in raw.items()}
    return {
        "config": {"slots": slots, "seed": seed, "modes": list(modes), "thresholds": asdict(thr),
                   "flow": asdict(cfg), "python": platform.python_version()},
        "notes": [
            "Ground-truth harm uses the x*y=k model (0.3% fee) on pool reserves read before the bundle.",
            "Layer-2 latency is anvil JSON-RPC simulation time (snapshot, execute, revert), an upper bound "
            "for an in-process builder; engine-only replay time is M1's timing_ms.",
            "Lookalike (jit/mm_reverse/xpool) bids are set just above the backrun bid so they get evaluated.",
        ],
        "summary": summary,
        "slots": raw,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--slots", type=int, default=200)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--modes", default=",".join(MODES))
    ap.add_argument("--rel-threshold", type=float, default=Thresholds.rel)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--anvil", default=None, help="path to anvil (default: PATH, ~/.foundry/bin, $ANVIL)")
    args = ap.parse_args()
    t0 = time.perf_counter()
    res = run(args.slots, args.seed, tuple(args.modes.split(",")), Thresholds(rel=args.rel_threshold),
              anvil_bin=args.anvil)
    res["config"]["wall_s"] = round(time.perf_counter() - t0, 1)
    args.out.write_text(json.dumps(res, indent=1) + "\n")
    print(table(res["summary"]))
    print("\nblocked / evaluated, by type")
    print(breakdown(res["summary"]))
    print(f"\nwrote {args.out} in {res['config']['wall_s']} s")


if __name__ == "__main__":
    main()
