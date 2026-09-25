"""Fail-closed cross-frame control candidates for a declared harm sink.

This is deliberately not a control-dependence proof.  It uses authenticated
frame lineage and the observed order of child returns/calls to surface
branch/returndata candidates that a value-only backward slice cannot see.
Static scope remains unresolved until a bounded CFG/post-dominator proof is
available.  The output is therefore suitable for review, never for a causal
verdict.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def _observation_index(provenance: dict) -> dict[str, tuple[int, dict]]:
    return {o["observation_id"]: (i, o) for i, o in enumerate(provenance.get("observations", []))}


def _frame_chain(provenance: dict, sink: str) -> list[str]:
    index = _observation_index(provenance)
    if sink not in index:
        raise ValueError(f"unknown sink observation: {sink}")
    frame_parent = provenance.get("frame_parent", {})
    frame = index[sink][1].get("frame_id")
    result = []
    seen = set()
    while frame and frame not in seen:
        seen.add(frame)
        result.append(frame)
        frame = frame_parent.get(frame)
    return result


def build_control_candidates(provenance: dict, sink: str) -> dict:
    observations = provenance.get("observations", [])
    index = _observation_index(provenance)
    values = {v["value_id"]: v for v in provenance.get("values", [])}
    chain = _frame_chain(provenance, sink)
    chain_set = set(chain)
    by_frame: dict[str, list[tuple[int, dict]]] = defaultdict(list)
    for i, observation in enumerate(observations):
        if observation.get("frame_id") in chain_set:
            by_frame[observation.get("frame_id")].append((i, observation))

    candidates = []
    for child in chain[:-1]:
        parent = provenance.get("frame_parent", {}).get(child)
        if not parent:
            continue
        child_positions = [i for i, o in enumerate(observations) if o.get("frame_id") == child]
        if not child_positions:
            continue
        child_start = min(child_positions)
        parent_events = [(i, o) for i, o in by_frame.get(parent, []) if i < child_start]
        # A branch after a returndata copy is the narrowest generic signal for
        # an authorization/oracle result being consumed before a child call.
        copy_positions = [i for i, o in parent_events if o.get("kind") == "returndata_copy"]
        lower_bound = max(copy_positions) if copy_positions else -1
        branches = [(i, o) for i, o in parent_events
                    if i > lower_bound and o.get("kind") == "branch_predicate"]
        for position, branch in branches[:8]:
            candidates.append({
                "candidate_id": branch["observation_id"],
                "kind": "control_candidate",
                "status": "REVIEW_REQUIRED_CONTROL_SCOPE_UNRESOLVED",
                "branch_frame": parent,
                "child_frame": child,
                "branch_pc": branch.get("pc"),
                "branch_target": branch.get("branch_target"),
                "branch_taken": branch.get("branch_taken"),
                "branch_position": position,
                "reason": "branch observed after returndata consumption and before descendant frame entry",
            })
        for position, observation in parent_events:
            if observation.get("kind") != "returndata_copy" or position < lower_bound:
                continue
            candidates.append({
                "candidate_id": observation["observation_id"],
                "kind": "cross_frame_return_candidate",
                "status": "AUTHENTICATED_RETURN_DATA_REVIEW_REQUIRED",
                "branch_frame": parent,
                "child_frame": child,
                "observation_position": position,
                "values": observation.get("values", []),
                "return_source_frames": sorted({
                    values[parent].get("frame_id")
                    for value_id in observation.get("values", [])
                    for parent in values.get(value_id, {}).get("parents", [])
                    if parent in values and values[parent].get("producer_opcode") == "FRAME_RETURN_DATA"
                }),
                "reason": "returndata consumed in parent before descendant frame entry",
            })

    # Stable ordering is important for blinded review and reproducibility.
    candidates.sort(key=lambda item: (item.get("branch_position", item.get("observation_position", 0)), item["candidate_id"]))
    source_frames = {frame for candidate in candidates for frame in candidate.get("return_source_frames", [])}
    frame_meta = provenance.get("frame_meta", {})
    return {
        "schema_version": "e5-control-candidate-slice-v1",
        "sink_observation_id": sink,
        "frame_chain": chain,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "frame_meta": {frame: frame_meta.get(frame, {}) for frame in (set(chain) | source_frames)},
        "interpretation": "Cross-frame control candidates only; static control scope is unresolved and no causal verdict is inferred.",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--sink-observation-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text())
    result = build_control_candidates(payload["provenance"], args.sink_observation_id)
    args.output.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
