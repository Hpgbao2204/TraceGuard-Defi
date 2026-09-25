"""Bind a declared protected-harm predicate to authenticated provenance.

The predicate is analyst/adapter supplied, but the matching is deterministic
and provenance-backed.  This separates harm-node declaration from downstream
graph construction and fails closed on ambiguity; it never creates a causal
label.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def _matches(observation: dict, provenance: dict, spec: dict) -> bool:
    if spec.get("kind") and observation.get("kind") != spec["kind"]:
        return False
    if spec.get("call_trace_index") is not None and observation.get("trace_index") != spec["call_trace_index"]:
        return False
    frame_id = observation.get("frame_id")
    meta = provenance.get("frame_meta", {}).get(frame_id, {})
    if spec.get("frame_id") and frame_id != spec["frame_id"]:
        return False
    if spec.get("frame_address") and str(meta.get("address", "")).lower() != spec["frame_address"].lower():
        return False
    if spec.get("pc") is not None and observation.get("pc") != spec["pc"]:
        return False
    required_value = spec.get("value")
    if required_value is not None:
        values = {v["value_id"]: v for v in provenance.get("values", [])}
        observed_values = [values.get(value_id, {}).get("value") for value_id in observation.get("values", [])]
        if required_value.lower() not in {str(value).lower() for value in observed_values if value is not None}:
            return False
    return True


def bind(provenance_run: dict, spec: dict) -> dict:
    provenance = provenance_run.get("provenance") or {}
    matches = [o for o in provenance.get("observations", []) if _matches(o, provenance, spec)]
    if len(matches) == 1:
        status = "HARM_NODE_BOUND"
        bound = matches[0]
    elif not matches:
        status = "NOT_OBSERVABLE"
        bound = None
    else:
        status = "AMBIGUOUS_HARM_NODE"
        bound = None
    return {
        "schema_version": "e5-harm-sink-binding-v1",
        "status": status,
        "predicate": spec,
        "match_count": len(matches),
        "bound_observation": bound,
        "causal_verdict": None,
        "interpretation": "Binding identifies an authenticated observation only; it does not establish harm magnitude or causal necessity.",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provenance", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = bind(json.loads(args.provenance.read_text()), json.loads(args.spec.read_text()))
    args.output.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
