"""Build the TraceGuard-DeFi dataset release (all data the paper uses) as one zip under dist/.

    python -m tools.build_dataset_release [--out dist] [--version v1]

Reads the local, git-ignored data (trace cache, proof-bound replay contexts, run outputs) and writes
dist/TraceGuard-DeFi_dataset_<version>.zip with a datasheet and SHA-256 checksums. Provider URLs are
replaced by neutral labels and local paths are removed; the build fails if any credential-like string or
local path survives. Replay contexts keep their proofs, so every replay can be re-verified offline.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "eval" / "results"
CACHE = ROOT / ".cache"

PROVIDER_PATTERNS = [
    (re.compile(r"https://[A-Za-z0-9.-]*alchemy\.com[^\"\s]*"), "<archive-provider>"),
    (re.compile(r"https://[A-Za-z0-9.-]*quiknode\.pro[^\"\s]*"), "<trace-provider>"),
]
LOCAL_PATTERNS = [re.compile(p, re.I) for p in (r"[A-Z]:\\\\(?:Dev|Users)[^\"\s]*", r"[A-Z]:/(?:Dev|Users)[^\"\s]*",
                                                  r"/c/Users/[^\"\s]*", r"/d/Dev/[^\"\s]*")]
FORBIDDEN = [re.compile(p, re.I) for p in (r"alchemy\.com/v2/[A-Za-z0-9_-]{12,}", r"quiknode\.pro/[A-Za-z0-9]{12,}",
                                           r"[a-z0-9-]+\.[a-z-]+\.quiknode\.pro", r"apikey=[A-Za-z0-9]{8,}",
                                           r"[A-Z]:[/\\\\]+Users[/\\\\]+[^/\\\\\"\s]+")]
TEXT_SUFFIXES = {".json", ".jsonl", ".md", ".txt", ".tsv", ".csv"}


def sanitize_text(text: str) -> str:
    for pat, label in PROVIDER_PATTERNS:
        text = pat.sub(label, text)
    for pat in LOCAL_PATTERNS:
        text = pat.sub("<local-path>", text)
    return text


def copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.suffix in TEXT_SUFFIXES and src.stat().st_size < 64 * 1024 * 1024:
        dst.write_text(sanitize_text(src.read_text(encoding="utf-8", errors="strict")), encoding="utf-8")
    else:
        shutil.copyfile(src, dst)


def copy_tree(src: Path, dst: Path, skip: tuple[str, ...] = ()) -> None:
    for f in sorted(src.rglob("*")):
        if f.is_file() and not any(part in skip for part in f.relative_to(src).parts):
            copy_file(f, dst / f.relative_to(src))


def refresh_manifest_hashes(ctx: Path) -> None:
    """Contexts record input hashes of their files; recompute them after sanitizing."""
    man = ctx / "manifest.json"
    if not man.is_file():
        return
    doc = json.loads(man.read_text(encoding="utf-8"))
    hashes = doc.get("input_hashes") or {}
    for name in list(hashes):
        f = ctx / name
        if f.is_file():
            hashes[name] = hashlib.sha256(f.read_bytes()).hexdigest()
    man.write_text(json.dumps(doc, indent=2), encoding="utf-8")


def copy_context(src: Path, dst: Path) -> None:
    copy_tree(src, dst, skip=("proof_chunks",))
    refresh_manifest_hashes(dst)


DATASHEET = """# TraceGuard-DeFi dataset ({version})

Data behind the paper "TraceGuard-DeFi: Leakage-Aware Screening and Confound-Aware Counterfactual Replay for
DeFi Exploits and Ordering Attacks". Code: the TraceGuard-DeFi repository (commit given in the paper).

## Contents

| Folder | Content | Used in |
|---|---|---|
| `screening/` | Trace cache of 80 DeFiHackLabs exploits (2024-2026) and 3,381 background transactions from 37 anchor blocks (`e1_trace_cache.jsonl.gz`, with its release manifest); the incident catalogue (`incidents.jsonl`); the frozen block-grouped split, test predictions, near-negative cohorts, robustness folds, and the revision analyses (ablation, baselines, bootstrap, repeated splits, calibration, out-of-fold scores) | RQ1 |
| `exploit_queue/manifests/` | The 20-case queue: frozen and mechanically amended victim/attacker boundaries, and the frozen v2/v3 factor rules on both | RQ2, RQ3 |
| `exploit_queue/contexts/` | 20 proof-bound replay contexts: block, prefix transactions, receipts, prestates and poststates, EIP-1186 proofs against the parent state root, 256 ancestor headers | RQ2, RQ3 |
| `exploit_queue/nethermind/` | Independent re-execution on a Nethermind v1.39.3 archive node and the per-case comparison | RQ2 |
| `exploit_queue/rq3_results/` | Stage-2 outcome summaries for frozen/amended boundaries and rules v2/v3 | RQ3 |
| `exploit_queue/boundary_audit/` | Call traces and deployment lookups used by the mechanical boundary amendment | RQ3 |
| `exploit_queue/guards/` | Guard-restoration manifest, compiled-runtime lock, results, and the three proof-bound contexts with the shadow address's non-existence proof | RQ3 |
| `controls/` | Euler Finance and Alkimiya contexts and positive-control results | RQ3 |
| `sandwiches/` | 40 weakly labelled mainnet sandwiches (blocks 22,100,000-22,100,188): labels, 40 proof-bound contexts, and drop/placebo results | RQ4 |
| `simulation/` | Builder simulation outputs, 5 seeds x 200 slots, and the pooled table | RQ4 |

## Provenance and collection

All transactions, receipts, state, and proofs are public Ethereum mainnet data, collected in 2026 through an
archive JSON-RPC endpoint (proofs, `eth_getProof`) and trace endpoints (`prestateTracer`, `callTracer`).
Provider URLs are replaced by `<archive-provider>` / `<trace-provider>`. Proofs bind every replayed state
item to the block's parent state root, so the contexts can be verified without trusting the provider.
Exploit labels and incident metadata derive from the DeFiHackLabs catalogue
(https://github.com/SunWeb3Sec/DeFiHackLabs, Apache License 2.0). Background transactions are unlabelled
open-world transactions and are not verified benign. Sandwich labels are heuristic (same-pool front- and
back-run by one contract around another sender's swap).

## Intended use and limitations

Evaluating transaction screening and counterfactual replay of DeFi incidents. The exploit queue is small
(20 cases), victim boundaries are analyst declarations (a published amendment corrects several), and
sandwich labels are weak. The data contain no private keys, credentials, or personal data beyond public
blockchain addresses.

## License

Our annotations, manifests, and results: CC BY 4.0. DeFiHackLabs-derived metadata: Apache 2.0 (attribution
above). Public blockchain data carries no additional restriction.

## Integrity

`SHA256SUMS` lists every file. Verify with `sha256sum -c SHA256SUMS` (Linux/macOS) or the provided
`verify.py`.
"""

VERIFY = '''import hashlib, sys
from pathlib import Path
root = Path(__file__).resolve().parent
bad = 0
for line in (root / "SHA256SUMS").read_text().splitlines():
    digest, name = line.split("  ", 1)
    if hashlib.sha256((root / name).read_bytes()).hexdigest() != digest:
        print("MISMATCH", name); bad += 1
print("all files verified" if not bad else f"{bad} mismatches"); sys.exit(1 if bad else 0)
'''


def build(out_dir: Path, version: str) -> Path:
    stage = out_dir / f"TraceGuard-DeFi_dataset_{version}"
    if stage.exists():
        shutil.rmtree(stage)
    s = stage / "screening"
    copy_file(ROOT / "eval" / "artifacts" / "e1_trace_cache.jsonl.gz", s / "e1_trace_cache.jsonl.gz")
    copy_file(ROOT / "eval" / "artifacts" / "cache_release_manifest.json", s / "cache_release_manifest.json")
    copy_file(ROOT / "corpus" / "incidents.jsonl", s / "incidents.jsonl")
    runs = RES / "runs"
    copy_file(runs / "p7-screening-split-corrected-20260912-r2" / "split_manifest.json", s / "split_manifest.json")
    for name in ("metrics.json", "model.json", "test_predictions.json"):
        copy_file(runs / "p7-screening-model-corrected-20260912-r2" / name, s / "model" / name)
    copy_tree(runs / "p7-near-negative-20260912-r1", s / "near_negative")
    copy_tree(runs / "p7-robustness-20260912-r1", s / "robustness")
    copy_file(CACHE / "revision" / "stage1.json", s / "revision_analyses.json")

    q = stage / "exploit_queue"
    for name in ("fixed20_cases.json", "fixed20_cases_amended.json", "fixed20_factors.json", "fixed20_factors_v3.json",
                 "fixed20_factors_amended_v2.json", "fixed20_factors_amended_v3.json"):
        copy_file(ROOT / "eval" / "rq3" / name, q / "manifests" / name)
    for ctx in sorted((RES / "m4" / "b2-contexts-fresh").iterdir()):
        copy_context(ctx, q / "contexts" / ctx.name)
    for name in ("m4_comparison_summary.json", "m4_b2_vs_liquify_20.json"):
        copy_file(RES / "m4" / name, q / "nethermind" / name)
    for folder in ("rq3_final_v2_new", "rq3_final_v3_new", "rq3_final_amended_v2", "rq3_final_amended_v3"):
        copy_file(CACHE / folder / "summary.json", q / "rq3_results" / f"{folder.replace('_new', '_frozen')}.json")
    copy_tree(CACHE / "rq3_amend", q / "boundary_audit", skip=("pass2.log", "pass3.log"))
    for f in ("guards.json", "guards.lock.json"):
        copy_file(ROOT / "eval" / "rq3" / "guards" / f, q / "guards" / f)
    copy_file(CACHE / "rq3_guard" / "results.json", q / "guards" / "results.json")
    for ctx in sorted((CACHE / "rq3_guard" / "ctx").iterdir()):
        copy_context(ctx, q / "guards" / "contexts" / ctx.name)

    c = stage / "controls"
    copy_file(CACHE / "rq3_controls" / "controls.json", c / "controls.json")
    copy_context(RES / "runs" / "b2-context-flashloan-euler-finance-16817996", c / "euler-finance-16817996")
    copy_context(RES / "m6" / "dependency-contexts" / "alkimiya", c / "alkimiya-22146340")

    w = stage / "sandwiches"
    for name in ("labels.json", "results.json"):
        copy_file(CACHE / "revision" / "sandwich" / name, w / name)
    for ctx in sorted((CACHE / "revision" / "sandwich" / "ctx").iterdir()):
        copy_context(ctx, w / "contexts" / ctx.name)

    m = stage / "simulation"
    for f in sorted((CACHE / "mev_sim").glob("seed*.json")) + [CACHE / "mev_sim" / "rq4_table.json"]:
        copy_file(f, m / f.name)

    (stage / "DATASHEET.md").write_text(DATASHEET.format(version=version), encoding="utf-8")
    (stage / "verify.py").write_text(VERIFY, encoding="utf-8")

    leaks = []
    for f in sorted(stage.rglob("*")):
        if f.is_file() and f.suffix in TEXT_SUFFIXES:
            text = f.read_text(encoding="utf-8", errors="ignore")
            for pat in FORBIDDEN + LOCAL_PATTERNS:
                if pat.search(text):
                    leaks.append(f"{f.relative_to(stage)}: {pat.pattern}")
    if leaks:
        raise SystemExit("refusing to package, sensitive strings remain:\n" + "\n".join(leaks[:20]))

    files = sorted(f for f in stage.rglob("*") if f.is_file())
    sums = [f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.relative_to(stage).as_posix()}" for f in files]
    (stage / "SHA256SUMS").write_text("\n".join(sums) + "\n", encoding="utf-8")

    archive = out_dir / f"{stage.name}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in sorted(stage.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(out_dir).as_posix())
    shutil.rmtree(stage)
    return archive


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=ROOT / "dist")
    ap.add_argument("--version", default="v1")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    archive = build(args.out, args.version)
    print(f"wrote {archive} ({archive.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
