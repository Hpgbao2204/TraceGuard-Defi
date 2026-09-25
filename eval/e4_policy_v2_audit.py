"""Derive a protocol-v2 policy audit from an existing Stage-2 run.

The historical rows remain untouched. Missing controls or protected harm
evidence are represented as INCONCLUSIVE by the new policy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from core.artifacts import ArtifactStore
from eval.e4.policy_v2 import apply_policy_rows


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(source_run: Path, runs_dir: Path, run_id: str) -> Path:
    source_run = source_run.resolve()
    source = json.loads((source_run / "systematic_subset_summary.json").read_text())
    rows = []
    for case in source["results"]:
        baseline = next((row for row in case.get("rows", []) if row.get("mutation") == "fidelity"), None)
        if baseline is None:
            continue
        for mutation in case.get("rows", []):
            if mutation.get("mutation") == "fidelity":
                continue
            derived = apply_policy_rows(case.get("rows", []))
            decision = next(row for row in derived if row.get("mutation") == mutation.get("mutation"))
            rows.append({
                "case_id": case["case_id"],
                "mutation": mutation.get("mutation"),
                "legacy_verdict": mutation.get("verdict"),
                "protocol_v2_decision": {
                    "verdict": decision["verdict"],
                    "causal_evidence": decision["causal_evidence"],
                    "reason_code": decision["policy_reason"],
                    "defense_blocked": decision.get("defense_blocked", False),
                },
                "policy_adapter": "eval.e4.policy_v2.apply_policy_rows",
                "source_row_status": mutation.get("outcome"),
            })
    store = ArtifactStore(runs_dir)
    store.create_run(run_id, {
        "experiment": "E4-stage2-policy-v2-audit",
        "protocol_version": "counterfactual-validity-v2",
        "source_run": source_run.name,
        "inputs": {"source_summary_sha256": _sha256(source_run / "systematic_subset_summary.json")},
        "design": {"derived_only": True, "historical_rows_unchanged": True},
    })
    counts = Counter(row["protocol_v2_decision"]["verdict"] for row in rows)
    store.write_json(run_id, "policy_v2_rows.json", rows)
    store.write_json(run_id, "policy_v2_summary.json", {"source_run": source_run.name, "n_mutations": len(rows), "verdict_counts": dict(counts)})
    store.finalize(run_id)
    return runs_dir / run_id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run", type=Path, required=True)
    parser.add_argument("--runs-dir", type=Path, default=Path("eval/results/runs"))
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    print(json.dumps({"run_dir": str(audit(args.source_run, args.runs_dir, args.run_id))}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
