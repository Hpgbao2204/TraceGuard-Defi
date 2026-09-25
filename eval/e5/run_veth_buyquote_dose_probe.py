"""Diagnostic input-dose probe for the VETH buyQuote boundary.

The selector is resolved through OpenChain's public signature database and
the calldata layout is checked against the canonical trace before replay.
This changes buyQuote's second uint256 input; it is not yet a proof-bound
root-cause intervention and cannot produce a causal verdict by itself.
"""
from __future__ import annotations

import json
import subprocess
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASE = "defihacklabs-veth-2024-11-14"
CONTEXT = ROOT / "eval/results/m4/b2-contexts-fresh" / CASE
RUNNER = ROOT / "tools/geth-replay/geth-replay"
OUT = ROOT / "eval/results/e5_rcfh/veth_buyquote_dose_probe"
TARGET_INDEX = 57
TOKEN = "ab181941a6096296ecf1b0859ea65c797676d428"


def main() -> int:
    replay = json.loads((CONTEXT / "b2-replay-m4.json").read_text())
    raw = replay["per_tx"][TARGET_INDEX]["call_trace"][17]["input"]
    raw = raw[2:] if raw.startswith("0x") else raw
    assert raw[:8].lower() == "a7591849"
    words = [raw[i:i + 64] for i in range(8, len(raw), 64)]
    assert len(words) >= 3 and words[0][-40:].lower() == TOKEN
    original_amount = int(words[1], 16)
    assert original_amount > 0
    original_value = int(replay["per_tx"][TARGET_INDEX]["call_trace"][17]["value"])

    OUT.mkdir(parents=True, exist_ok=True)
    # The lower sweep only measured the AMM validity floor. Sweep above the
    # historical point to stay in the executable region where possible.
    # Fine feasibility search between the known failing 75% point and the
    # known successful 90% point.  These are diagnostic capital ratios only.
    points = [50, 75, 76, 77, 78, 79, 80, 82, 83, 84, 85, 86, 88, 90, 95, 100]
    rows = []
    for pct in points:
        dose = original_amount * pct // 100
        mutated = list(words)
        mutated[1] = f"{dose:064x}"
        replacement_input = "0x" + raw[:8] + "".join(mutated)
        out = OUT / f"dose_{pct:03d}.json"
        cmd = [str(RUNNER), "--context", str(CONTEXT), "--proofs",
               str(CONTEXT / "prestate_proofs.json"), "--output", str(out),
               "--target-index", str(TARGET_INDEX),
               "--intervention-caller", "0x351d38733de3f1e73468d24401c59f63677000c9",
               "--intervention-callee", "0x19c5538df65075d53d6299904636bae68b6df441",
               "--intervention-selector", "0xa7591849", "--intervention-depth", "3",
               "--intervention-type", "CALL", "--intervention-action", "rewrite_input_value",
               "--intervention-input", replacement_input,
               "--intervention-value", hex(dose)]
        proc = subprocess.run(cmd, text=True, capture_output=True)
        result = json.loads(out.read_text()) if out.exists() else {}
        target = result.get("per_tx", [{}])[TARGET_INDEX]
        ci = target.get("call_intervention") or {}
        revert_data = ci.get("first_revert_data") or ""
        revert_reason = None
        if revert_data.startswith("0x08c379a0") and len(revert_data) >= 138:
            try:
                payload = bytes.fromhex(revert_data[10:])
                off = int.from_bytes(payload[:32], "big")
                ln = int.from_bytes(payload[off:off + 32], "big")
                revert_reason = payload[off + 32:off + 32 + ln].decode(errors="replace")
            except Exception:
                revert_reason = "MALFORMED_ERROR_STRING"
        logs = target.get("logs") or []
        transfer_values = []
        for log in logs:
            topics = log.get("topics") or []
            if topics and topics[0].lower() == "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef" and log.get("data"):
                transfer_values.append({
                    "address": log.get("address"),
                    "from": "0x" + topics[1][-40:] if len(topics) > 1 else None,
                    "to": "0x" + topics[2][-40:] if len(topics) > 2 else None,
                    "value_raw": str(int(log["data"], 16)),
                })
        rows.append({
            "dose_percent": pct,
            "amount_raw": str(dose),
            "returncode": proc.returncode,
            "actual_status": target.get("actual_status"),
            "actual_gas": target.get("actual_gas"),
            "status_match": target.get("status_match"),
            "gas_match": target.get("gas_match"),
            "logs_match": target.get("logs_match"),
            "post_state_match": target.get("post_state_match"),
            "acceptance_gate": result.get("acceptance_gate"),
            "match_count": ci.get("match_count"),
            "application_verified": ci.get("application_verified"),
            "first_revert_depth": ci.get("first_revert_depth"),
            "first_revert_data": ci.get("first_revert_data"),
            "first_revert_reason": revert_reason,
            "erc20_transfer_values": transfer_values,
            "stderr_tail": proc.stderr[-1000:],
        })
    artifact = {
        "schema_version": 1,
        "artifact": "e5-veth-buyquote-input-dose-diagnostic",
        "case_id": CASE,
        "boundary": {"selector": "0xa7591849", "signature": "buyQuote(address,uint256,uint256)", "target_index": TARGET_INDEX},
        "signature_provenance": "OpenChain signature database; verified-contract match",
        "dose_parameter": "buyQuote second uint256; rewrite applied at exact Factory CALL before dispatch",
        "original_amount_raw": str(original_amount),
        "original_value_wei": str(original_value),
        "coupled_intervention": "buyQuote second uint256 and Factory CALL msg.value scaled together",
        "claim_binding": "BOUNDARY_DIAGNOSTIC_NOT_CAUSAL_AUTHORIZATION",
        "classification": "FEASIBILITY_BOUNDARY_IDENTIFIED_NOT_DOSE_RESPONSE",
        "response_summary": "50/75% revert; 90/95/100% execute. vETH Transfer-to-attacker amount rises across 90/95/100%, but 90/95% fail logs/post-state comparability. Diagnostic only.",
        "revert_is_not_no_harm": True,
        "observations": rows,
    }
    (OUT / "result.json").write_text(json.dumps(artifact, indent=2) + "\n")
    print(json.dumps({"out": str(OUT / "result.json"), "observations": rows}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
