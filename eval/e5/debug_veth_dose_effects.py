"""Persist a structural diff for the VETH coupled dose runs."""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "eval/results/e5_rcfh/veth_buyquote_dose_probe"
OUT = BASE / "debug_effect_diff.json"


def event_shape(log):
    topics = log.get("topics") or []
    return (log.get("address", "").lower(), tuple(x.lower() for x in topics), len(log.get("data", "")))


def frame_shape(frame):
    return (frame.get("event"), frame.get("type"), frame.get("from", "").lower(),
            frame.get("to", "").lower(), frame.get("depth"), frame.get("reverted"), frame.get("error"))


def main():
    rows = []
    baseline = json.loads((BASE / "dose_100.json").read_text())["per_tx"][57]
    for pct in (90, 95):
        target = json.loads((BASE / f"dose_{pct:03d}.json").read_text())["per_tx"][57]
        same_frame_shape = [frame_shape(x) for x in baseline["call_trace"]] == [frame_shape(x) for x in target["call_trace"]]
        same_event_shape = [event_shape(x) for x in baseline["logs"]] == [event_shape(x) for x in target["logs"]]
        payload_diffs = sum(a.get("data") != b.get("data") for a, b in zip(baseline["logs"], target["logs"]))
        rows.append({
            "dose_percent": pct,
            "same_call_trace_shape": same_frame_shape,
            "same_event_shape_and_order": same_event_shape,
            "baseline_log_count": len(baseline["logs"]),
            "dose_log_count": len(target["logs"]),
            "payload_data_differences": payload_diffs,
            "status": target["actual_status"],
            "gas": target["actual_gas"],
            "logs_match": target["logs_match"],
            "post_state_match": target["post_state_match"],
            "interpretation": "same execution topology; state-dependent payloads and post-state differ"
        })
    OUT.write_text(json.dumps({
        "schema_version": 1,
        "artifact": "e5-veth-dose-structural-effect-diff",
        "case_id": "defihacklabs-veth-2024-11-14",
        "baseline": "dose_100",
        "rows": rows,
        "conclusion": "No control-flow or event-shape divergence was detected at 90/95%; logs/post-state mismatch is value propagation through the same AMM/liquidity path, not a newly selected branch. This still fails comparable-replay gates because the committed values differ from baseline.",
        "unit_warning": "Token decimals were not inferred from a reported loss; raw event values remain raw units until a frozen decimals observation is added."
    }, indent=2) + "\n")
    print(OUT)


if __name__ == "__main__":
    main()
