"""Freeze a grouped screening split as a new immutable run artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from core.artifacts import ArtifactStore

from .e1_train import build_dataset
from .grouped_split_v2 import split_rows
from core.protocol import SCREENING_PROTOCOL_VERSION
from .run_manifest import git_revision

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CACHE = ROOT / "eval" / "results" / "e1_trace_cache.jsonl"
DEFAULT_RUNS = ROOT / "eval" / "results" / "runs"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def freeze(cache: Path, runs_dir: Path, run_id: str, seed: int = 42) -> Path:
    """Build and persist a split manifest without fitting or reading test labels."""
    cache = cache.resolve()
    ds = build_dataset(cache)
    manifest = split_rows(ds["rows"], seed=seed)
    store = ArtifactStore(runs_dir)
    try:
        cache_display = str(cache.relative_to(ROOT))
    except ValueError:
        cache_display = f"<external>/{cache.name}"
    run_dir = store.create_run(
        run_id,
        {
            "experiment": "E1-screening-grouped-split",
            "protocol_version": SCREENING_PROTOCOL_VERSION,
            "code_provenance": git_revision(ROOT),
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "inputs": {
                "cache_path": cache_display,
                "cache_sha256": _sha256(cache),
                "row_count": len(ds["rows"]),
                "attack_count": sum(row["label"] == "attack" for row in ds["rows"]),
                "benign_count": sum(row["label"] == "benign" for row in ds["rows"]),
            },
            "split": {
                "seed": seed,
                "target_fractions": list(manifest.target_fractions),
                "freeze_before_fit": True,
            },
        },
    )
    store.write_json(run_id, "split_manifest.json", manifest.as_dict())
    store.finalize(run_id)
    return run_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)
    path = freeze(args.cache, args.runs_dir, args.run_id, args.seed)
    print(json.dumps({"run_dir": str(path), "status": "split-frozen"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
