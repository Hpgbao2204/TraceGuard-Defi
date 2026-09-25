"""Run Morpho capital substitution at the internal ERC-20 transfer seam."""
import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from eval.e4.erc20_slot_resolver import resolve_balance_slot

ROOT = Path(__file__).resolve().parents[1]
CONTEXT = ROOT / "results/m6/dependency-contexts/alkimiya"
OUTDIR = ROOT / "results/e4_causal_v4"
TOKEN = "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599"
PROVIDER = "0xbbbbbbbbbb9cc5e90e3b3af64bdaf62c37eeffcb"
BORROWER = "0x80bf7db69556d9521c03461978b8fc731dbbd4e4"
TRANSFER_SELECTOR = "0xa9059cbb"
AMOUNT = 1_000_000_000


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runner", type=Path, required=True)
    args = ap.parse_args()
    pre = json.loads((CONTEXT / "prestates.json").read_text())[0]["trace"]
    proofs = json.loads((CONTEXT / "prestate_proofs.json").read_text())["proofs"]
    resolved = resolve_balance_slot(TOKEN, pre, proofs, [BORROWER, PROVIDER,
                                                         "0x4585fe77225b41b697c938b018e2ac67ac5a20c0",
                                                         "0xf3f84ce038442ae4c4dcb6a8ca8bacd7f28c9bde"])
    key = next(k for a, k in resolved["hits"] if a == BORROWER)
    provider_key = next(k for a, k in resolved["hits"] if a == PROVIDER)
    before = int(pre[TOKEN]["storage"][key], 16)
    provider_before = int(pre[TOKEN]["storage"][provider_key], 16)
    for mode in ("sham", "counterfactual"):
        output = OUTDIR / f"alkimiya_morpho_capital_substitution_{mode}.json"
        cmd = [str(args.runner), "--context", str(CONTEXT), "--proofs",
               str(CONTEXT / "prestate_proofs.json"), "--output", str(output),
               "--target-index", "0", "--intervention-caller", PROVIDER,
               "--intervention-callee", TOKEN, "--intervention-selector",
               TRANSFER_SELECTOR, "--intervention-depth", "2",
               "--intervention-type", "CALL", "--intervention-occurrence", "1",
               "--intervention-action", "observe_only" if mode == "sham" else "substitute"]
        if mode == "counterfactual":
            cmd += ["--target-storage", f"{TOKEN}:{key}=0x{before + AMOUNT:x}",
                    "--target-storage", f"{TOKEN}:{provider_key}=0x{provider_before - AMOUNT:x}",
                    "--intervention-output", "0x" + "0" * 63 + "1"]
        proc = subprocess.run(cmd, text=True, capture_output=True)
        result = json.loads(output.read_text()) if output.exists() else {}
        result["v4_capital_substitution"] = {
            "mode": mode, "slot_index": resolved["slot_index"],
            "borrower_slot": key, "balance_before": str(before),
            "balance_after": str(before + AMOUNT) if mode == "counterfactual" else str(before),
            "provider_balance_slot": provider_key,
            "provider_balance_before": str(provider_before),
            "provider_balance_after": str(provider_before - AMOUNT) if mode == "counterfactual" else str(provider_before),
            "runner_returncode": proc.returncode, "runner_stderr": proc.stderr[-2000:],
            "semantic_target": "internal provider ERC20 transfer; outer flashLoan/callback unchanged",
        }
        output.write_text(json.dumps(result, indent=2) + "\n")
        print(mode, json.dumps({k: result.get(k) for k in ("all_gas_match", "all_status_match", "all_logs_match", "acceptance_gate")}, sort_keys=True))


if __name__ == "__main__":
    main()
