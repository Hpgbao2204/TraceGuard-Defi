"""Check the generated metric artifact and manuscript linkage."""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def main() -> int:
    metrics = json.loads((ROOT / "eval/results/paper_metrics.json").read_text())
    required = ("source_commit", "evaluation_artifact_sha256", "main", "structural_near_negative")
    missing = [key for key in required if key not in metrics]
    tex = (ROOT / "paper/main.tex").read_text()
    if "\\input{generated_metrics.tex}" not in tex:
        missing.append("paper_generated_metrics_input")
    if missing:
        print("metric lineage check failed:", ", ".join(missing))
        return 1
    print("metric lineage: PASS")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
