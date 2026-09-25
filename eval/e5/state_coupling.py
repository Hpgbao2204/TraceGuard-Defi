"""Pure state-coupling analysis for E5.

This module only constructs dependency groups. It does not mutate a fork,
infer protocol semantics, or issue a causal verdict.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping


@dataclass(frozen=True)
class StateNode:
    node_id: str
    kind: str
    address: str | None = None
    key: str | None = None
    provenance: str | None = None


@dataclass(frozen=True)
class StateEdge:
    source: str
    target: str
    relation: str
    provenance: str | None = None


@dataclass(frozen=True)
class ConsistencyPredicate:
    predicate_id: str
    kind: str
    inputs: tuple[str, ...]
    output: str | None = None
    params: tuple[int, ...] = ()
    source: str | None = None
    confidence: str | None = None
    version: str | None = None


@dataclass(frozen=True)
class EvidenceEvent:
    event_id: str
    kind: str
    node_id: str
    trace_index: int
    provenance: str


PREDICATE_KINDS = frozenset({
    "EQUAL",
    "DELTA_EQUAL",
    "SUM",
    "RANGE",
    "PACKED_FIELD",
    "DERIVED",
})
PREDICATE_CONFIDENCE = frozenset({"HIGH", "MEDIUM", "LOW"})
EVIDENCE_EVENT_KINDS = frozenset({
    "STATE_READ",
    "STATE_WRITE",
    "EXTERNAL_CALL",
    "TOKEN_TRANSFER",
    "HARM",
})


FORCE_MUTATION_RELATIONS = frozenset({
    "CONSISTENCY_REQUIRES",
    "MIRRORS",
})
OBSERVATIONAL_RELATIONS = frozenset({
    "DERIVES_FROM",
    "READ_DEPENDENCY",
    "HARM_OBSERVATION",
})
EDGE_RELATIONS = FORCE_MUTATION_RELATIONS | OBSERVATIONAL_RELATIONS


class StateCouplingError(ValueError):
    """Raised when a coupling graph is incomplete or malformed."""


def nodes_from_state_diff(
    prestate: Mapping[str, Mapping[str, object]],
    poststate: Mapping[str, Mapping[str, object]],
    *,
    source: str,
) -> tuple[StateNode, ...]:
    """Normalize changed B2 diff cells into provenance-tagged state nodes.

    The adapter deliberately creates no dependency edges. A balance/storage
    relationship must be supplied by a later semantic or trace-derived layer.
    """
    if not source or not source.strip():
        raise StateCouplingError("state-diff source provenance is required")
    def canonical_accounts(raw):
        return {str(address).lower(): value for address, value in raw.items()}

    pre_accounts = canonical_accounts(prestate)
    post_accounts = canonical_accounts(poststate)
    addresses = set(pre_accounts) | set(post_accounts)
    result: list[StateNode] = []
    for address in sorted(addresses):
        before = pre_accounts.get(address) or {}
        after = post_accounts.get(address) or {}
        if before.get("balance") != after.get("balance"):
            result.append(StateNode(
                f"native:{address.lower()}",
                "native_balance",
                address.lower(),
                "balance",
                source,
            ))
        before_storage = {
            str(key).lower(): value for key, value in (before.get("storage") or {}).items()
        }
        after_storage = {
            str(key).lower(): value for key, value in (after.get("storage") or {}).items()
        }
        storage_keys = set(before_storage) | set(after_storage)
        for key in sorted(storage_keys):
            if before_storage.get(key) != after_storage.get(key):
                result.append(StateNode(
                    f"storage:{address.lower()}:{key.lower()}",
                    "storage",
                    address.lower(),
                    key.lower(),
                    source,
                ))
    return tuple(result)


def _validate_node(node: StateNode) -> None:
    if not node.node_id or not node.kind:
        raise StateCouplingError("state node requires node_id and kind")
    if node.kind in {"storage", "erc20_balance", "native_balance"}:
        if not node.address or not node.key:
            raise StateCouplingError(
                f"{node.kind} node requires address and key: {node.node_id}"
            )


def _validate_typed_edge(edge: StateEdge, node_ids: set[str]) -> None:
    if edge.source not in node_ids or edge.target not in node_ids:
        raise StateCouplingError(
            f"edge references unknown node: {edge.source}, {edge.target}"
        )
    if edge.relation not in EDGE_RELATIONS:
        raise StateCouplingError(f"unsupported edge relation: {edge.relation}")
    if not edge.provenance or edge.provenance.strip().upper() in {
        "AMBIGUOUS",
        "UNKNOWN",
        "UNRESOLVED",
    }:
        raise StateCouplingError(
            f"typed edge requires provenance: {edge.source}->{edge.target}"
        )


def _validate_predicate(predicate: ConsistencyPredicate) -> None:
    if not predicate.predicate_id or predicate.kind not in PREDICATE_KINDS:
        raise StateCouplingError(f"unsupported predicate: {predicate.predicate_id}")
    if not predicate.inputs:
        raise StateCouplingError(f"predicate has no inputs: {predicate.predicate_id}")
    if not predicate.source or not predicate.version:
        raise StateCouplingError(
            f"predicate requires source and version: {predicate.predicate_id}"
        )
    if predicate.confidence not in PREDICATE_CONFIDENCE:
        raise StateCouplingError(
            f"predicate requires recognized confidence: {predicate.predicate_id}"
        )
    if predicate.kind == "RANGE" and len(predicate.params) != 2:
        raise StateCouplingError("RANGE requires min and max parameters")
    if predicate.kind == "PACKED_FIELD" and len(predicate.params) != 2:
        raise StateCouplingError("PACKED_FIELD requires offset and width")
    if predicate.kind in {"SUM", "DERIVED"} and not predicate.output:
        raise StateCouplingError(f"{predicate.kind} requires an output node")


def recover_candidate_edges(
    events: Iterable[EvidenceEvent],
    *,
    harm_event_id: str,
) -> dict[str, object]:
    """Suggest observational edges from ordered execution evidence.

    This is deliberately not a mutation authorizer. It only links a state read
    to later transfer/call/harm events and labels every edge as dynamic
    evidence. Ambiguous ordering or duplicate event IDs fails closed.
    """
    event_list = list(events)
    ids = [event.event_id for event in event_list]
    if len(set(ids)) != len(ids):
        raise StateCouplingError("duplicate evidence event id")
    for event in event_list:
        if event.kind not in EVIDENCE_EVENT_KINDS:
            raise StateCouplingError(f"unsupported evidence event: {event.kind}")
        if event.trace_index < 0 or not event.provenance:
            raise StateCouplingError(f"invalid evidence provenance: {event.event_id}")
    ordered = sorted(event_list, key=lambda event: (event.trace_index, event.event_id))
    if any(left.trace_index == right.trace_index and left.event_id != right.event_id
           for left, right in zip(ordered, ordered[1:])):
        raise StateCouplingError("ambiguous same-index evidence ordering")
    harm = next((event for event in ordered if event.event_id == harm_event_id), None)
    if harm is None or harm.kind != "HARM":
        raise StateCouplingError("harm event is missing or malformed")
    reads = [event for event in ordered
             if event.kind == "STATE_READ" and event.trace_index < harm.trace_index]
    downstream = [event for event in ordered
                   if event.trace_index > 0 and event.trace_index <= harm.trace_index
                   and event.kind in {"EXTERNAL_CALL", "TOKEN_TRANSFER", "HARM"}]
    edges = []
    for read in reads:
        for event in downstream:
            if read.trace_index < event.trace_index:
                relation = "HARM_OBSERVATION" if event.kind == "HARM" else "READ_DEPENDENCY"
                edges.append(StateEdge(
                    read.node_id, event.node_id, relation,
                    f"{read.provenance};{event.provenance}",
                ))
    return {
        "status": "CANDIDATE_EDGES",
        "edges": tuple(edges),
        "resolver_version": "state-coupling-evidence-v1",
        "mutation_authorized": False,
    }


def state_consistency_gate(
    values: Mapping[str, int],
    nodes: Iterable[StateNode],
    edges: Iterable[StateEdge],
    predicates: Iterable[ConsistencyPredicate],
    *,
    seeds: Iterable[str],
) -> dict[str, object]:
    """Pre-replay gate for a proposed coupled state.

    This gate proves only that the declared closure and predicates are
    sufficiently evidenced. It never applies a mutation or authorizes causal
    replay.
    """
    node_list = list(nodes)
    edge_list = list(edges)
    seed_set = set(seeds)
    closure = minimal_mutation_set(seed_set, node_list, edge_list)
    predicate_result = evaluate_predicates(values, predicates)
    missing_closure_values = sorted(
        node_id for node_id in closure if node_id not in values
    )
    complete = (
        predicate_result["status"] == "CONSISTENT"
        and not missing_closure_values
    )
    if missing_closure_values and predicate_result["status"] == "CONSISTENT":
        predicate_result = {
            **predicate_result,
            "status": "UNKNOWN",
            "reason": "MISSING_CLOSURE_VALUE",
            "missing": missing_closure_values,
        }
    return {
        "status": "READY_FOR_REPLAY_PRECHECK" if complete else "NOT_TESTABLE",
        "closure": closure,
        "predicate_result": predicate_result,
        "missing_closure_values": tuple(missing_closure_values),
        "mutation_authorized": False,
        "resolver_version": "state-coupling-gate-v1",
    }


def evaluate_predicates(
    values: Mapping[str, int],
    predicates: Iterable[ConsistencyPredicate],
) -> dict[str, object]:
    """Evaluate explicit state constraints without inferring semantics.

    Missing values or predicates are UNKNOWN. A malformed or ambiguous
    predicate raises StateCouplingError before any result is published.
    """
    predicate_list = list(predicates)
    if not predicate_list:
        return {
            "status": "UNKNOWN",
            "predicates": [],
            "reason": "NO_CONSISTENCY_PREDICATE",
            "resolver_version": "state-coupling-v1",
        }
    for predicate in predicate_list:
        _validate_predicate(predicate)
    results: list[dict[str, object]] = []
    for predicate in predicate_list:
        ids = list(predicate.inputs)
        required = set(ids)
        if predicate.output:
            required.add(predicate.output)
        missing = sorted(node_id for node_id in required if node_id not in values)
        if missing:
            results.append({
                "predicate_id": predicate.predicate_id,
                "status": "UNKNOWN",
                "reason": "MISSING_VALUE",
                "missing": missing,
            })
            continue
        actual = [values[node_id] for node_id in ids]
        expected: int | None = None
        if predicate.kind == "EQUAL":
            ok = len(set(actual)) == 1
        elif predicate.kind == "DELTA_EQUAL":
            ok = len(actual) == 2 and actual[0] == actual[1]
        elif predicate.kind == "SUM":
            expected = sum(actual)
            ok = values[predicate.output] == expected
        elif predicate.kind == "RANGE":
            low, high = predicate.params
            ok = low <= actual[0] <= high
        elif predicate.kind == "PACKED_FIELD":
            offset, width = predicate.params
            mask = (1 << width) - 1
            ok = ((actual[0] >> offset) & mask) == values[predicate.output]
        elif predicate.kind == "DERIVED":
            # DERIVED is intentionally declarative in A2; the producer must
            # provide the expected output as the final input value.
            ok = values[predicate.output] == actual[0]
        else:
            raise StateCouplingError(f"unhandled predicate: {predicate.kind}")
        results.append({
            "predicate_id": predicate.predicate_id,
            "status": "CONSISTENT" if ok else "INCONSISTENT",
            "reason": None if ok else "PREDICATE_FAILED",
            "expected": expected,
        })
    statuses = {item["status"] for item in results}
    status = (
        "INCONSISTENT" if "INCONSISTENT" in statuses
        else "UNKNOWN" if "UNKNOWN" in statuses
        else "CONSISTENT"
    )
    return {
        "status": status,
        "predicates": results,
        "resolver_version": "state-coupling-v1",
    }


def minimal_mutation_set(
    target: str | Iterable[str],
    nodes: Iterable[StateNode],
    edges: Iterable[StateEdge],
) -> tuple[str, ...]:
    """Resolve the smallest explicitly forced mutation closure.

    Traversal follows only directed consistency/mirror relations. Observation
    and read-dependency edges never pull protected or derived nodes into the
    mutation set.
    """
    node_list = list(nodes)
    node_map = {node.node_id: node for node in node_list}
    if len(node_map) != len(node_list):
        raise StateCouplingError("duplicate state node id")
    for node in node_list:
        _validate_node(node)
    edge_list = list(edges)
    for edge in edge_list:
        _validate_typed_edge(edge, set(node_map))
    if isinstance(target, str):
        seeds = {target}
    else:
        seeds = set(target)
    if not seeds or not seeds.issubset(node_map):
        unknown = sorted(seeds - set(node_map))
        raise StateCouplingError(f"unknown target node(s): {unknown}")

    outgoing: dict[str, list[str]] = {node_id: [] for node_id in node_map}
    for edge in edge_list:
        if edge.relation in FORCE_MUTATION_RELATIONS:
            outgoing[edge.source].append(edge.target)

    closure = set(seeds)
    pending = sorted(seeds)
    while pending:
        current = pending.pop()
        for neighbour in sorted(outgoing[current]):
            if neighbour not in closure:
                closure.add(neighbour)
                pending.append(neighbour)
    return tuple(sorted(closure))


def connected_components(
    nodes: Iterable[StateNode],
    edges: Iterable[tuple[str, str]],
) -> list[tuple[str, ...]]:
    """Return deterministic connected components for an explicit graph."""
    node_list = list(nodes)
    node_map = {node.node_id: node for node in node_list}
    if len(node_map) != len(node_list):
        raise StateCouplingError("duplicate state node id")
    for node in node_map.values():
        _validate_node(node)

    adjacency = {node_id: set() for node_id in node_map}
    for left, right in edges:
        if left not in node_map or right not in node_map:
            raise StateCouplingError(f"edge references unknown node: {left}, {right}")
        adjacency[left].add(right)
        adjacency[right].add(left)

    components: list[tuple[str, ...]] = []
    unseen = set(node_map)
    while unseen:
        root = min(unseen)
        stack = [root]
        unseen.remove(root)
        component = []
        while stack:
            current = stack.pop()
            component.append(current)
            for neighbour in sorted(adjacency[current], reverse=True):
                if neighbour in unseen:
                    unseen.remove(neighbour)
                    stack.append(neighbour)
        components.append(tuple(sorted(component)))
    return sorted(components)


def coupled_intervention_set(
    target: str,
    nodes: Iterable[StateNode],
    edges: Iterable[tuple[str, str]],
) -> tuple[str, ...]:
    """Return the full explicit coupling group containing target."""
    node_list = list(nodes)
    if target not in {node.node_id for node in node_list}:
        raise StateCouplingError(f"unknown target node: {target}")
    for component in connected_components(node_list, list(edges)):
        if target in component:
            return component
    raise StateCouplingError(f"target has no component: {target}")


def consistency_report(
    nodes: Iterable[StateNode],
    edges: Iterable[tuple[str, str]],
    *,
    declared_mutation: Iterable[str],
) -> dict[str, object]:
    """Report whether a declared mutation covers its full coupling group."""
    node_list = list(nodes)
    mutation = tuple(sorted(set(declared_mutation)))
    components = connected_components(node_list, list(edges))
    covered = set(mutation)
    missing: list[str] = []
    for component in components:
        if covered.intersection(component):
            missing.extend(node for node in component if node not in covered)
    return {
        "complete": not missing and bool(mutation),
        "declared_mutation": mutation,
        "missing_coupled_nodes": tuple(sorted(set(missing))),
        "components": components,
        "resolver_version": "state-coupling-v1",
    }
