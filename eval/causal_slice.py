"""Deterministic backward slicing over an evidence-bound event graph.

The slicer discovers candidates from graph dependencies. It does not infer
causality: counterfactual replay and validity gates remain separate.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any, Iterable, Mapping


def event_signature(event: Mapping[str, Any]) -> tuple[Any, ...]:
    """Comparable prefix fields; excludes gas and post-intervention effects."""
    return (
        event.get("event"), event.get("type"), event.get("depth"),
        str(event.get("from", "")).lower(), str(event.get("to", "")).lower(),
        str(event.get("input", "")).lower(),
        str(event.get("output", "")).lower(),
        bool(event.get("reverted", False)),
    )


def assert_prefix_match(factual: list[Mapping[str, Any]], counterfactual: list[Mapping[str, Any]], intervention_index: int) -> dict[str, Any]:
    """Check equality only before the declared intervention point."""
    limit = min(intervention_index, len(factual), len(counterfactual))
    mismatches = [i for i in range(limit) if event_signature(factual[i]) != event_signature(counterfactual[i])]
    return {
        "valid": not mismatches and len(factual) >= intervention_index and len(counterfactual) >= intervention_index,
        "intervention_index": intervention_index,
        "compared_events": limit,
        "mismatches": mismatches,
    }


def assert_non_circular_outcome(intervention_fields: Iterable[str], outcome_fields: Iterable[str]) -> None:
    overlap = set(intervention_fields) & set(outcome_fields)
    if overlap:
        raise ValueError(f"outcome predicate encodes intervention fields: {sorted(overlap)}")


def backward_slice(nodes: Iterable[Mapping[str, Any]], edges: Iterable[Mapping[str, str]], sink: str) -> list[str]:
    incoming: dict[str, list[str]] = defaultdict(list)
    known = {str(node["id"]) for node in nodes}
    for edge in edges:
        src, dst = str(edge["src"]), str(edge["dst"])
        if src in known and dst in known:
            incoming[dst].append(src)
    seen: set[str] = set()
    queue = deque([sink])
    while queue:
        current = queue.popleft()
        if current in seen:
            continue
        seen.add(current)
        queue.extend(incoming.get(current, []))
    return sorted(seen)


def classify_candidates(nodes: Iterable[Mapping[str, Any]], sliced: Iterable[str]) -> list[dict[str, Any]]:
    ids = set(sliced)
    return [dict(node) for node in nodes if str(node["id"]) in ids and node.get("role") != "outcome"]
