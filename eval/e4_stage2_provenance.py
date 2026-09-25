"""Verify checksums referenced by a completed E4 Stage-2 run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from eval.e4_stage2_subset import ROOT, sha256_file


def audit(run_dir: Path) -> dict:
    run_dir = run_dir.resolve()
    summary = json.loads((run_dir / "systematic_subset_summary.json").read_text())
    mismatches: list[str] = []
    checked = 0
    for case in summary.get("results", []):
        for relative, expected in (case.get("artifact_hashes") or {}).items():
            path = ROOT / relative
            checked += 1
            if not path.is_file() or sha256_file(path) != expected:
                mismatches.append(relative)
    result = {
        "schema_version": 1,
        "run_id": run_dir.name,
        "source_summary_sha256": sha256_file(run_dir / "systematic_subset_summary.json"),
        "artifacts_checked": checked,
        "checksum_mismatches": mismatches,
        "status": "PASS" if not mismatches else "FAIL",
    }
    (run_dir / "provenance_audit.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.run)
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
