"""Verify that the large project preserves the runnable small-project API.

This is intentionally a structural parity check, not a source copy tool.  The
large project has stricter E4/B2 gates and additional interventions, so copying
the small project's generated result script would be unsafe.  We verify the
portable public surface and report extensions separately.
"""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def public_symbols(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_"):
                names.add(node.name)
    return names


def compare(source: Path, target: Path) -> dict:
    source_symbols = public_symbols(source)
    target_symbols = public_symbols(target)
    return {
        "source": str(source.relative_to(ROOT)),
        "target": str(target.relative_to(ROOT)),
        "source_symbols": sorted(source_symbols),
        "missing_in_target": sorted(source_symbols - target_symbols),
        "target_extensions": sorted(target_symbols - source_symbols),
        "pass": source_symbols <= target_symbols,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "TraFiSec")
    args = parser.parse_args()
    source = args.source.resolve()
    checks = [
        compare(source / "core" / "mutate.py", ROOT / "core" / "mutate.py"),
        compare(source / "eval" / "e4_necessity.py", ROOT / "eval" / "e4_necessity.py"),
        compare(source / "eval" / "e4" / "execution.py", ROOT / "eval" / "e4" / "execution.py"),
        compare(source / "eval" / "e4" / "models.py", ROOT / "eval" / "e4" / "models.py"),
    ]
    report = {"schema_version": 1, "checks": checks,
              "pass": all(item["pass"] for item in checks),
              "excluded_nonportable_source": [
                  "eval/e4_evaluate_all.py: hard-coded historical/frame-local counts",
              ]}
    print(json.dumps(report, indent=2))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
