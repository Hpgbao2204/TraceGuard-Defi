#!/usr/bin/env python3
"""Run SummerFi NAV operator sham/counterfactual probes.

This is a preregistered, single-site diagnostic probe.  The intervention
replaces the selected zombie-Ark ``totalAssets()`` return with zero, modelling
the claim's "offboarded Ark contributes no NAV" counterfactual.  Occurrences
are run separately because the current Geth CLI accepts one occurrence per
invocation; these runs are not yet a composite all-occurrences verdict.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CASE = "defihacklabs-summerfi-2026-07-06"
CONTEXT = ROOT / "eval/results/m4/b2-contexts-fresh" / CASE
RUNNER = ROOT / "tools/geth-replay/geth-replay"
OUTDIR = ROOT / "eval/results/e5_rcfh/summerfi_nav_operator_probe"
FLEET = "0x98c49e13bf99d7cad8069faa2a370933ec9ecf17"
ARK = "0x61d7063041d83c8ca3e42c39181dfd14b3bc76c2"
SELECTOR = "0x01e1d114"
DEPTH = "6"
ZERO_OUTPUT = "0x" + "0" * 64


def run(mode: str, occurrence: int) -> dict:
    output = OUTDIR / f"{mode}_occurrence_{occurrence}.json"
    command = [
        str(RUNNER),
        "--context", str(CONTEXT),
        "--proofs", str(CONTEXT / "prestate_proofs.json"),
        "--output", str(output),
        "--target-index", "0",
        "--intervention-caller", FLEET,
        "--intervention-callee", ARK,
        "--intervention-selector", SELECTOR,
        "--intervention-depth", DEPTH,
        "--intervention-type", "STATICCALL",
        "--intervention-occurrence", str(occurrence),
        "--intervention-action", (
            "substitute_passthrough" if mode == "sham" else "substitute"
        ),
    ]
    # The runner validates an output flag even for passthrough shams; the
    # passthrough path ignores it and executes the original child call.
    command += ["--intervention-output", ZERO_OUTPUT]
    proc = subprocess.run(command, text=True, capture_output=True)
    result = json.loads(output.read_text()) if output.exists() else {}
    tx = (result.get("per_tx") or [{}])[0]
    intervention = tx.get("call_intervention") or {}
    return {
        "mode": mode,
        "occurrence": occurrence,
        "command": command,
        "returncode": proc.returncode,
        "acceptance_gate": result.get("acceptance_gate"),
        "status_match": tx.get("status_match"),
        "gas_match": tx.get("gas_match"),
        "logs_match": tx.get("logs_match"),
        "post_state_match": tx.get("post_state_match"),
        "actual_status": tx.get("actual_status"),
        "match_count": intervention.get("match_count"),
        "application_verified": intervention.get("application_verified"),
        "first_revert_depth": intervention.get("first_revert_depth"),
        "first_revert_data": intervention.get("first_revert_data"),
        "stderr_tail": proc.stderr[-2000:],
        "artifact": str(output),
    }


def main() -> None:
    OUTDIR.mkdir(parents=True, exist_ok=True)
    runs = []
    # Depth-6 matching occurrences are 4 and 5.  The raw trace's all-depth
    # NAV list numbers the same calls 6 and 7 because it also includes the
    # depth-4 and depth-9 calls.
    for occurrence in (4, 5):
        runs.append(run("sham", occurrence))
        runs.append(run("counterfactual", occurrence))
    manifest = {
        "schema_version": 1,
        "artifact": "e5-summerfi-nav-accounting-operator-probe",
        "case_id": CASE,
        "operator": {
            "name": "offboarded_ark_zero_total_assets",
            "semantics": "replace only the selected zombie-Ark totalAssets() return with zero",
            "boundary": {
                "caller": FLEET,
                "callee": ARK,
                "selector": SELECTOR,
                "signature_annotation": "totalAssets()",
                "call_type": "STATICCALL",
                "depth": 6,
            },
            "replacement_output": ZERO_OUTPUT,
        },
        "scope": "single-site probes; occurrences 6 and 7 are not yet composed into one run",
        "runs": runs,
        "authorization": "diagnostic_probe_only_until_multi_occurrence_semantics_and_protected_harm_adapter_are frozen",
        "source_sha256": {
            "b2_context": hashlib.sha256((CONTEXT / "b2-replay-m4.json").read_bytes()).hexdigest(),
            "prestate_proofs": hashlib.sha256((CONTEXT / "prestate_proofs.json").read_bytes()).hexdigest(),
        },
    }
    path = OUTDIR / "result.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
