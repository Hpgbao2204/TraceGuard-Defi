"""Harm-anchored slicing over authenticated dynamic provenance.

This module builds only edges present in the provenance artifact: value-parent
edges and value-to-observation edges. It deliberately does not add temporal
call or storage edges and never consumes validated mechanism references.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict, deque
from pathlib import Path


def build_graph(provenance: dict, sink: str) -> tuple[list[dict], list[dict]]:
    nodes: list[dict] = []
    edges: list[dict] = []
    values = {v["value_id"]: v for v in provenance.get("values", [])}
    for value in values.values():
        nodes.append({
            "id": value["value_id"], "node_type": "value",
            "producer_opcode": value.get("producer_opcode"),
            "frame_id": value.get("frame_id"), "pc": value.get("pc"),
            "depth": value.get("depth"),
        })
        for parent in value.get("parents", []):
            if parent in values:
                edges.append({"src": parent, "dst": value["value_id"], "kind": "value_parent"})
    for observation in provenance.get("observations", []):
        oid = observation["observation_id"]
        nodes.append({
            "id": oid, "node_type": "observation",
            "observation_kind": observation.get("kind"),
            "frame_id": observation.get("frame_id"), "pc": observation.get("pc"),
            "depth": observation.get("depth"), "role": "outcome" if oid == sink else "observation",
        })
        for value_id in observation.get("values", []):
            if value_id in values:
                edges.append({"src": value_id, "dst": oid, "kind": "observation_input"})
    return nodes, edges


def slice_and_rank(nodes: list[dict], edges: list[dict], sink: str) -> list[dict]:
    incoming: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        incoming[edge["dst"]].append(edge["src"])
    distance = {sink: 0}
    queue = deque([sink])
    while queue:
        current = queue.popleft()
        for parent in incoming.get(current, []):
            if parent not in distance:
                distance[parent] = distance[current] + 1
                queue.append(parent)
    node_by_id = {node["id"]: node for node in nodes}
    candidates = []
    for node_id, dist in distance.items():
        node = node_by_id[node_id]
        if node.get("node_type") != "value":
            continue
        opcode = str(node.get("producer_opcode") or "")
        if opcode.startswith("AUTHENTICATED_"):
            continue
        enriched = dict(node)
        enriched["slice_distance"] = dist
        enriched["rank_score"] = 1000 - dist
        candidates.append(enriched)
    return sorted(candidates, key=lambda item: (-item["rank_score"], item["slice_distance"], item["id"]))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--sink-observation-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text())
    provenance = payload["provenance"]
    observation_ids = {o["observation_id"] for o in provenance.get("observations", [])}
    if args.sink_observation_id not in observation_ids:
        raise SystemExit(f"unknown sink observation: {args.sink_observation_id}")
    nodes, edges = build_graph(provenance, args.sink_observation_id)
    candidates = slice_and_rank(nodes, edges, args.sink_observation_id)
    sliced = {item["id"] for item in candidates} | {args.sink_observation_id}
    args.output.write_text(json.dumps({
        "schema_version": "e5-provenance-harm-slice-v1",
        "source": str(args.input),
        "sink_observation_id": args.sink_observation_id,
        "node_count": len(nodes), "edge_count": len(edges),
        "slice_node_count": len(sliced), "candidate_count": len(candidates),
        "candidate_generation": "provenance-only; no validated references",
        "candidates": candidates,
    }, indent=2) + "\n")


if __name__ == "__main__":
    main()
