"""Run the strict provenance engine on Geth opcode telemetry."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path

from eval.e5.dynamic_provenance import DynamicProvenance, ProvenanceError


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def open_text(path: Path):
    return gzip.open(path, "rt") if path.suffix == ".gz" else path.open()


def normalize(event: dict) -> dict:
    out = dict(event)
    out["frameId"] = out.get("frame_id")
    out["storageContextAddress"] = out.get("storage_context")
    out["returnData"] = out.get("return_data")
    out["returnDataSourceFrame"] = out.get("return_data_source_frame")
    out["callTraceIndex"] = out.get("call_trace_index")
    out["callInput"] = out.get("call_input")
    out["code"] = out.get("code")
    out["stack"] = out.get("stack", [])
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path)
    ap.add_argument("--input-ndjson", type=Path)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--allow-frame-bootstrap", action="store_true", help="explicitly allow suffix telemetry to initialize a frame from its first observed stack")
    args = ap.parse_args()
    if bool(args.input) == bool(args.input_ndjson):
        ap.error("provide exactly one of --input or --input-ndjson")
    target_index = 0
    event_count = 0
    if args.input_ndjson:
        def ndjson_events():
            nonlocal event_count
            with open_text(args.input_ndjson) as handle:
                for line in handle:
                    if line.strip():
                        event_count += 1
                        yield normalize(json.loads(line))
        events = ndjson_events()
        source_path = args.input_ndjson
    else:
        payload = json.loads(args.input.read_text())
        target_index = int(payload["target_index"])
        target = payload["per_tx"][target_index]
        events = (normalize(e) for e in target.get("opcode_telemetry", []))
        event_count = len(target.get("opcode_telemetry", []))
        source_path = args.input
    result = {
        "schema_version": "e5-dynamic-provenance-run-v1",
        "source_sha256": sha256(source_path),
        "target_index": target_index,
        "input_event_count": event_count,
        "strict": True,
        "provenance": None,
        "status": None,
        "error": None,
    }
    try:
        model = DynamicProvenance(strict=True, allow_frame_bootstrap=args.allow_frame_bootstrap).consume(events)
        result["input_event_count"] = event_count
        result["provenance"] = model.to_dict()
        result["status"] = "PROVENANCE_COMPLETE_WITH_BOOTSTRAP" if model.shadow_bootstrapped_frames else "PROVENANCE_COMPLETE"
        result["summary"] = {
            "value_count": len(model.values),
            "observation_count": len(model.observations),
            "observation_kinds": sorted({o.kind for o in model.observations}),
            "frame_count": len({v.frame_id for v in model.values.values() if v.frame_id}),
            "storage_value_count": sum(1 for v in model.values.values() if v.producer_opcode == "SLOAD"),
            "state_write_observation_count": sum(1 for o in model.observations if o.kind == "state_write"),
        }
    except ProvenanceError as exc:
        result["status"] = "PROVENANCE_INCOMPLETE"
        result["error"] = str(exc)
    args.output.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
