"""Build a local, checksum-pinned release manifest for verified artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.artifacts import ArtifactStore


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(root: Path, output: Path) -> dict:
    selections = {
        "stage1_split": "eval/results/runs/e1-grouped-v2-freeze-20260909-r2/split_manifest.json",
        "stage1_model": "eval/results/runs/e1-grouped-v2-fit-20260909-r3/model.json",
        "stage1_e3": "eval/results/runs/e3-grouped-v2-paired-20260910-r7/paired_metrics.json",
        "stage1_e3_equal_size": "eval/results/runs/e3-grouped-v2-paired-20260910-r7/equal_size_metrics.json",
        "stage1_grouped_robustness": "eval/results/runs/e1e2-grouped-robustness-v2-20260910-r5/grouped_robustness.json",
        "stage1_grouped_input": "eval/results/runs/e1e2-grouped-robustness-v2-20260910-r5/input_manifest.json",
        "stage1_grouped_predictions": "eval/results/runs/e1e2-grouped-robustness-v2-20260910-r5/predictions.json",
        "stage1_grouped_split": "eval/results/runs/e1e2-grouped-robustness-v2-20260910-r5/group_manifest.json",
        "stage2_policy_audit": "eval/results/runs/e4-stage2-gate-policy-audit-20260909-r6/policy_v2_summary.json",
        "stage2_pilot": "eval/results/runs/e4-stage2-v2-pilot-20260909-r4/systematic_subset_summary.json",
        "stage2_review_packets": "eval/results/runs/e4-stage2-v2-pilot-20260909-r4/review_packets_v3/reviewer_a.json",
        "e6_latency": "eval/results/runs/e6-latency-v2-20260909/e6_latency.csv",
    }
    artifacts = {}
    missing = []
    incomplete = []
    for name, relative in selections.items():
        path = root / relative
        if not path.is_file():
            missing.append(relative)
            continue
        runs_root = root / "eval" / "results" / "runs"
        try:
            run_id = path.parent.relative_to(runs_root).parts[0]
            ArtifactStore(runs_root).require_complete(run_id)
        except (ValueError, OSError) as exc:
            incomplete.append({"artifact": relative, "reason": str(exc)})
            continue
        artifacts[name] = {"path": relative, "sha256": digest(path)}
    if incomplete:
        raise ValueError("release contains incomplete or unverified runs: "
                         + json.dumps(incomplete, ensure_ascii=False))
    manifest = {
        "schema_version": 1,
        "manifest_id": "trafisec-proposal-v2-local-20260909",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "manifest_valid" if not missing else "manifest_incomplete",
        "research_status": "incomplete",
        "method_protocol": "proposal-v2; policy-v2; grouped-screening-v2",
        "artifacts": artifacts,
        "missing": missing,
        "limitations": [
            "Stage-2 selection is an internal five-case pilot, not fixed-20.",
            "Independent reviewer votes are pending.",
            "E5 whole-cohort fidelity and Stage-2 replay latency remain pending.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    output = args.output or args.root / "eval/results/release_manifest_v2.json"
    result = build(args.root.resolve(), output.resolve())
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "manifest_valid" else 1


if __name__ == "__main__":
    raise SystemExit(main())
