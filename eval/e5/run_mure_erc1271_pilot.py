"""Run the E5 MureDistribution ERC-1271 sham and intervention pilot."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from core.mutate import ERC1271ValidationSubstitution

ROOT = Path(__file__).resolve().parents[2]
CASE = "defihacklabs-muredistribution-2026-05-21"
CONTEXT = ROOT / "eval/results/m4/b2-contexts-fresh" / CASE
OUTDIR = ROOT / "eval/results/e5_rcfh/mure_erc1271_pilot"
RUNNER = ROOT / "tools/geth-replay/geth-replay"


def main() -> None:
    replay = json.loads((CONTEXT / "b2-replay-m4.json").read_text())
    target = replay["per_tx"][replay["target_index"]]
    # Exit index 19 is the return from the exact STATICCALL at enter index 18.
    original_output = target["call_trace"][19]["output"]
    mutation = ERC1271ValidationSubstitution(
        caller="0x365083717efb17f3895290ba38f20f568c7a4d8a",
        callee="0x26e5415c5ba86b4a521aaebf538623b9f32cd467",
        depth=4,
    )
    OUTDIR.mkdir(parents=True, exist_ok=True)
    results = []
    for mode, output in (
        ("sham", original_output),
        ("counterfactual", "0x" + "0" * 64),
    ):
        descriptor = mutation.descriptor(output=output, mode=mode)
        if mode == "sham":
            descriptor["intervention_action"] = "substitute_passthrough"
        out = OUTDIR / f"{mode}.json"
        cmd = [str(RUNNER), "--context", str(CONTEXT), "--proofs",
               str(CONTEXT / "prestate_proofs.json"), "--output", str(out),
               "--target-index", str(replay["target_index"])]
        for key, value in descriptor.items():
            if key == "mode":
                continue
            flag = "--" + key.replace("_", "-")
            cmd.extend([flag, str(value)])
        proc = subprocess.run(cmd, text=True, capture_output=True)
        result = json.loads(out.read_text()) if out.exists() else {}
        result["e5_erc1271_pilot"] = {
            "mode": mode,
            "command": cmd,
            "returncode": proc.returncode,
            "stderr_tail": proc.stderr[-2000:],
            "original_output": original_output,
            "replacement_output": output,
            "descriptor": descriptor,
        }
        out.write_text(json.dumps(result, indent=2) + "\n")
        results.append({"mode": mode, "returncode": proc.returncode,
                        "acceptance_gate": result.get("acceptance_gate"),
                        "all_status_match": result.get("all_status_match"),
                        "all_logs_match": result.get("all_logs_match"),
                        "all_gas_match": result.get("all_gas_match")})
    print(json.dumps(results, sort_keys=True))


if __name__ == "__main__":
    main()
