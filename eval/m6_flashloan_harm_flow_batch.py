"""Extract ERC-20 transfer-flow candidates from proof-bound receipts."""
import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
STATUS = ROOT / "eval/results/m6_flashloan_20_status_matrix.json"
TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

def main():
    out = []
    rows = json.loads(STATUS.read_text()).get("cases", [])
    run_dirs = list((ROOT / "eval/results/runs").glob("b2-context-flashloan-*/case.json"))
    by_tx = {}
    for case_file in run_dirs:
        try:
            c = json.loads(case_file.read_text())
            by_tx[str(c.get("tx_hash", "")).lower()] = case_file.parent
        except (OSError, ValueError):
            continue
    for row in rows:
        name, tx = row["name"], row["tx_hash"].lower()
        path = by_tx.get(tx)
        if path is None or not (path / "receipts.json").exists():
            out.append({"case": name, "tx_hash": tx, "status": "MISSING_OBSERVATION",
                        "harm_status": "INCONCLUSIVE_MISSING_RECEIPT"})
            continue
        receipts = json.loads((path / "receipts.json").read_text())
        if not receipts:
            out.append({"case": name, "tx_hash": tx, "status": "MISSING_OBSERVATION",
                        "harm_status": "INCONCLUSIVE_EMPTY_RECEIPTS"})
            continue
        target = receipts[-1]["receipt"]
        sender, created = None, []
        run_files = sorted(path.glob("b2-run-*.json"), key=lambda x: x.stat().st_mtime)
        if run_files:
            try:
                run = json.loads(run_files[-1].read_text())
                tx_rows = [x for x in run.get("per_tx", []) if str(x.get("tx_hash", "")).lower() == tx]
                if tx_rows:
                    trace = tx_rows[-1].get("call_trace", [])
                    root = next((x for x in trace if x.get("event") == "enter" and x.get("depth") == 0), None)
                    sender = (root or {}).get("from")
                    created = [x.get("to") for x in trace if x.get("event") == "enter" and x.get("type") in {"CREATE", "CREATE2"} and x.get("to")]
            except (OSError, ValueError):
                pass
        flows = []
        native_flows = []
        if run_files and tx_rows:
            for i, frame in enumerate(trace):
                if frame.get("event") == "enter" and frame.get("type") == "CALL":
                    raw_value = frame.get("value")
                    if raw_value not in (None, "<nil>", "0", 0, "0x0"):
                        try:
                            amount = int(str(raw_value), 0)
                            if amount:
                                native_flows.append({"token": "ETH", "from": frame.get("from", "").lower(),
                                                     "to": frame.get("to", "").lower(), "amount_raw": amount,
                                                     "trace_index": i})
                        except (TypeError, ValueError):
                            pass
        for log in target.get("logs", []):
            if log.get("topics", [None])[0].lower() == TOPIC and len(log["topics"]) >= 3:
                amount = log.get("data", "0x")
                if amount in ("0x", "0x0"):
                    continue
                flows.append({"token": log["address"].lower(), "from": "0x" + log["topics"][1][-40:].lower(), "to": "0x" + log["topics"][2][-40:].lower(), "amount_raw": int(amount, 16), "log_index": int(log["logIndex"], 16)})
        out.append({"case": name, "tx_hash": tx, "status": "FLOW_EXTRACTED",
                    "target_receipt_log_count": len(target.get("logs", [])),
                    "erc20_transfer_count": len(flows), "flows": flows,
                    "native_flows": native_flows,
                    "native_flow_count": len(native_flows),
                    "harm_status": "PROTECTED_ENTITY_PENDING",
                    "measurement_scope": "target receipt ERC20 Transfer ledger only",
                    "native_delta": "NOT_OBSERVED",
                    "protected_entity": "PENDING_ADJUDICATION"})
        out[-1].update({"sender": sender, "created_contracts": created})
    output = ROOT / "eval/results/m6_flashloan_harm_flow_batch.json"
    output.write_text(json.dumps({"schema_version": 1, "scope": "supplementary; flow preflight only", "cases": out}, indent=2) + "\n")
    print(json.dumps([(x["case"], x["status"], x.get("erc20_transfer_count")) for x in out], indent=2))

if __name__ == "__main__":
    main()
