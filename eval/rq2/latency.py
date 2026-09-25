"""RQ2 cost: repeated lean-mode replay of every frozen context, recording in-memory EVM time.

    python -m eval.rq2.latency --exe .cache\\geth-replay.exe --repeats 10

For each context in eval/results/m4/b2-contexts-fresh/<case>, runs `geth-replay -lean` N times, keeps
timing_ms (evm_replay, target_evm, context_load, proof_verify), acceptance_gate and output size, deletes the
per-run output, and writes .cache/rq2/latency.json plus a printed summary (median and p95 per case).
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTEXTS = ROOT / "eval" / "results" / "m4" / "b2-contexts-fresh"


def pct(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", required=True)
    ap.add_argument("--repeats", type=int, default=10)
    ap.add_argument("--contexts", type=Path, default=CONTEXTS)
    ap.add_argument("--out", type=Path, default=ROOT / ".cache" / "rq2")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    tmp = args.out / "_run.json"
    results = {}
    for ctx in sorted(d for d in args.contexts.iterdir() if (d / "case.json").exists()):
        case = json.loads((ctx / "case.json").read_text(encoding="utf-8"))
        n_tx = len(json.loads((ctx / "transactions.json").read_text(encoding="utf-8")))
        runs = []
        for _ in range(args.repeats):
            cmd = [args.exe, "-context", str(ctx), "-proofs", str(ctx / "prestate_proofs.json"),
                   "-output", str(tmp), "-lean"]
            t0 = time.perf_counter()
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
            wall = (time.perf_counter() - t0) * 1000
            if not tmp.exists():
                runs.append({"error": proc.stderr[-300:]})
                continue
            size = tmp.stat().st_size
            d = json.loads(tmp.read_text(encoding="utf-8"))
            tmp.unlink()
            t = d.get("timing_ms") or {}
            runs.append({"evm_replay": t.get("evm_replay"), "target_evm": t.get("target_evm"),
                         "context_load": t.get("context_load"), "proof_verify": t.get("proof_verify"),
                         "wall_ms": wall, "acceptance_gate": d.get("acceptance_gate"), "output_bytes": size})
        ok = [r for r in runs if "error" not in r]
        tgt = [r["target_evm"] for r in ok if r["target_evm"] is not None]
        results[ctx.name] = {"tx_index": case.get("tx_index"), "n_tx": n_tx, "runs": runs,
                             "accepted": all(r["acceptance_gate"] for r in ok) if ok else False,
                             "target_median_ms": statistics.median(tgt) if tgt else None,
                             "target_p95_ms": pct(tgt, 0.95) if tgt else None}
        r = results[ctx.name]
        print(f"{ctx.name[13:48]:36s} prefix={n_tx - 1:5d} accepted={r['accepted']!s:5s} "
              f"target median={r['target_median_ms']} p95={r['target_p95_ms']}")
    all_t = [x["target_evm"] for v in results.values() for x in v["runs"] if x.get("target_evm") is not None]
    summary = {"repeats": args.repeats, "cases": len(results),
               "accepted": sum(v["accepted"] for v in results.values()),
               "target_median_ms": statistics.median(all_t) if all_t else None,
               "target_p95_ms": pct(all_t, 0.95) if all_t else None}
    (args.out / "latency.json").write_text(json.dumps({"summary": summary, "cases": results}, indent=1),
                                           encoding="utf-8")
    print("summary", summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
