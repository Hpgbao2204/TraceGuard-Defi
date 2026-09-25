"""Run the proof-bound Alkimiya/Morpho trampoline as a v4 preflight.

This wrapper refuses to run unless the balance slot resolves uniquely from
the frozen prestate and storage proofs. It records the Geth result as
preflight evidence; it never assigns a causal verdict.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from eval.e4.erc20_slot_resolver import resolve_balance_slot


ROOT = Path(__file__).resolve().parents[1]
CONTEXT = ROOT / "results/m6/dependency-contexts/alkimiya"
DESCRIPTOR = ROOT / "results/e4_causal_v4/alkimiya_morpho_trampoline_descriptor.json"
OUT = ROOT / "results/e4_causal_v4/alkimiya_morpho_trampoline_preflight.json"
TOKEN = "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599"
BORROWER = "0x80bf7db69556d9521c03461978b8fc731dbbd4e4"
AMOUNT = 1_000_000_000


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runner", type=Path, required=True)
    ap.add_argument("--mode", choices=("counterfactual", "sham"), default="counterfactual")
    args = ap.parse_args()
    pre = json.loads((CONTEXT / "prestates.json").read_text())[0]["trace"]
    proofs = json.loads((CONTEXT / "prestate_proofs.json").read_text())["proofs"]
    desc = json.loads(DESCRIPTOR.read_text())
    resolved = resolve_balance_slot(TOKEN, pre, proofs, [BORROWER, desc["provider"],
                                                         "0x4585fe77225b41b697c938b018e2ac67ac5a20c0",
                                                         "0xf3f84ce038442ae4c4dcb6a8ca8bacd7f28c9bde"])
    borrower_key = next(k for a, k in resolved["hits"] if a == BORROWER)
    before = int(pre[TOKEN]["storage"][borrower_key], 16)
    after = before + AMOUNT
    output = OUT.with_name(f"alkimiya_morpho_trampoline_{args.mode}.json")
    cmd = [str(args.runner), "--context", str(CONTEXT), "--proofs",
           str(CONTEXT / "prestate_proofs.json"), "--output", str(output),
           "--target-index", "0"]
    if args.mode == "counterfactual":
        cmd += ["--target-storage", f"{TOKEN}:{borrower_key}=0x{after:x}"]
    cmd += ["--intervention-caller",
           desc["provider_caller"], "--intervention-callee", desc["provider"],
           "--intervention-selector", desc["provider_selector"],
           "--intervention-depth", str(desc["provider_depth"]),
           "--intervention-type", "CALL", "--intervention-action",
           "callback_trampoline" if args.mode == "counterfactual" else "callback_trampoline_transfer",
           "--intervention-callback-to", desc["callback_to"],
           "--intervention-callback-input", desc["callback_input"]]
    if args.mode == "sham":
        cmd += ["--intervention-capital-token", TOKEN, "--intervention-capital-amount", hex(AMOUNT)]
    proc = subprocess.run(cmd, text=True, capture_output=True)
    result = json.loads(output.read_text()) if output.exists() else {"runner_output_missing": True}
    execution_ok = bool(result.get("per_tx") and result["per_tx"][0].get("actual_status"))
    wrapper = {
        "schema_version": "e4-causal-v4-morpho-trampoline-preflight-v1",
        "status": "EXECUTED" if proc.returncode == 0 and result.get("mutation") and execution_ok else "EXECUTION_FAILED",
        "causal_verdict": None,
        "slot_index": resolved["slot_index"],
        "borrower": BORROWER,
        "balance_slot": borrower_key,
        "balance_before": str(before),
        "balance_after": str(after),
        "amount_added": str(AMOUNT),
        "runner_command": cmd,
        "runner_returncode": proc.returncode,
        "runner_stderr": proc.stderr[-4000:],
        "runner_output": result,
    }
    output.write_text(json.dumps(wrapper, indent=2) + "\n")
    print(json.dumps(wrapper, indent=2))
    return 0 if wrapper["status"] in {"EXECUTED", "EXECUTION_FAILED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
