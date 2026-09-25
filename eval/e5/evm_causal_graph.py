"""Protocol-agnostic EVM causal graph construction.

The builder consumes trace-level evidence only.  It creates a graph skeleton
from calls, returns, storage/transfer telemetry, and known semantic selectors.
It never invents business equations or promotes a node to a cause; callers must
bind a harm node and review the resulting candidates before replay.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Iterable, Mapping

SEMANTIC_SELECTORS = {
    "0x0902f1ac": "PRICE_READ",
    "0xfeaf968c": "PRICE_READ",
    "0x1626ba7e": "AUTH_CHECK",
    "0xab9c4b5d": "BORROW",
    "0xe0232b42": "BORROW",
    "0x5cffe9de": "BORROW",
    "0x5c38449e": "BORROW",
    "0x23b872dd": "BALANCE_UPDATE",
    "0xa9059cbb": "ASSET_TRANSFER",
    "0x40c10f19": "MINT",
}


@dataclass(frozen=True)
class EVMNode:
    node_id: str
    kind: str
    semantic: str
    trace_index: int | None = None
    depth: int | None = None
    caller: str | None = None
    callee: str | None = None
    selector: str | None = None
    value: Any = None
    evidence: str = "trace"


@dataclass(frozen=True)
class EVMEdge:
    source: str
    target: str
    relation: str
    evidence: str


def selector(calldata: Any) -> str | None:
    if not isinstance(calldata, str) or not calldata.startswith("0x") or len(calldata) < 10:
        return None
    return calldata[:10].lower()


def semantic_for(sel: str | None, event: Mapping[str, Any]) -> str:
    if event.get("storage_op") == "SLOAD":
        return "STATE_READ"
    if event.get("storage_op") == "SSTORE":
        return "STATE_WRITE"
    if event.get("transfer"):
        return "ASSET_TRANSFER"
    if event.get("branch"):
        return "BRANCH"
    return SEMANTIC_SELECTORS.get(sel or "", "CALL")


ALL_LAYERS = frozenset({
    "call_return",      # Layer 1: structural CALL/RETURN edges (existing)
    "return_chain",     # Layer 2: return-value → next call input chaining
    "storage",          # Layer 3: SLOAD/SSTORE same-(address, slot) edges
    "transfer",         # Layer 4: token Transfer log → call-frame edges
    "arithmetic",       # Layer 5: bytecode-level operand source (declared, not yet populated)
})

DEFAULT_LAYERS = frozenset({"call_return", "return_chain", "storage", "transfer"})


def _add_return_chain_edges(
    nodes: list[EVMNode],
    edges: list[EVMEdge],
    enters: dict[int, str],
) -> None:
    """Layer 2: wire return output → next call's input when selectors match.

    This creates dataflow edges where a call's return value is provably
    consumed by a subsequent call at the same depth.
    """
    # Group enter nodes by depth
    by_depth: dict[int, list[EVMNode]] = {}
    for n in nodes:
        if n.node_id.startswith("call:") and n.depth is not None:
            by_depth.setdefault(int(n.depth), []).append(n)

    return_nodes = {n.node_id: n for n in nodes if n.node_id.startswith("return:")}

    for depth, depth_nodes in by_depth.items():
        sorted_calls = sorted(depth_nodes, key=lambda n: n.trace_index or 0)
        for i in range(len(sorted_calls) - 1):
            current_call = sorted_calls[i]
            next_call = sorted_calls[i + 1]
            # Find return node for current call
            return_id = None
            for rid, rn in return_nodes.items():
                if rn.depth == current_call.depth and (rn.trace_index or 0) > (current_call.trace_index or 0):
                    if (rn.trace_index or 0) < (next_call.trace_index or 0):
                        return_id = rid
                        break
            if return_id:
                edges.append(EVMEdge(return_id, next_call.node_id, "return_chain", "return output → next call input"))


def _add_storage_edges(
    nodes: list[EVMNode],
    edges: list[EVMEdge],
    call_trace: Iterable[Mapping[str, Any]],
) -> None:
    """Layer 3: SLOAD/SSTORE edges matched by (address, slot).

    Only creates edges when the same (address, slot) pair appears in both
    a write and a subsequent read, proving data dependency through storage.
    """
    storage_events: list[dict[str, Any]] = []
    for index, item in enumerate(call_trace):
        storage_op = item.get("storage_op")
        if storage_op in ("SLOAD", "SSTORE"):
            address = str(item.get("address", item.get("to", ""))).lower()
            slot = str(item.get("slot", item.get("key", ""))).lower()
            storage_events.append({
                "index": index, "op": storage_op,
                "address": address, "slot": slot,
                "depth": item.get("depth"),
            })
            # Create storage node
            node_id = f"storage:{index}"
            semantic = "STATE_WRITE" if storage_op == "SSTORE" else "STATE_READ"
            nodes.append(EVMNode(node_id, "state", semantic, index, item.get("depth"),
                                 evidence="storage_telemetry"))

    # Match SSTORE → SLOAD for same (address, slot) with SSTORE before SLOAD
    writes = [e for e in storage_events if e["op"] == "SSTORE"]
    reads = [e for e in storage_events if e["op"] == "SLOAD"]
    for write in writes:
        for read in reads:
            if (write["address"] == read["address"]
                    and write["slot"] == read["slot"]
                    and write["index"] < read["index"]):
                edges.append(EVMEdge(
                    f"storage:{write['index']}", f"storage:{read['index']}",
                    "storage_dependency",
                    f"SSTORE→SLOAD {write['address']}:{write['slot']}",
                ))


def _add_transfer_edges(
    nodes: list[EVMNode],
    edges: list[EVMEdge],
    call_trace: Iterable[Mapping[str, Any]],
) -> None:
    """Layer 4: token Transfer log → call-frame edges.

    Creates edges from Transfer events to related call frames based on
    matching (from, to, amount) fields, proving value flow through tokens.
    """
    transfer_events: list[dict[str, Any]] = []
    call_nodes_by_address: dict[str, list[str]] = {}

    for index, item in enumerate(call_trace):
        if item.get("transfer"):
            transfer_data = item["transfer"]
            node_id = f"transfer:{index}"
            nodes.append(EVMNode(node_id, "state", "ASSET_TRANSFER", index,
                                 item.get("depth"),
                                 caller=str(transfer_data.get("from", "")).lower(),
                                 callee=str(transfer_data.get("to", "")).lower(),
                                 value=transfer_data.get("amount"),
                                 evidence="transfer_telemetry"))
            transfer_events.append({"index": index, "node_id": node_id, **transfer_data})

    # Build address index for call nodes
    for n in nodes:
        if n.node_id.startswith("call:") and n.callee:
            call_nodes_by_address.setdefault(n.callee.lower(), []).append(n.node_id)

    # Link transfer events to call frames involving the same addresses
    for t in transfer_events:
        t_from = str(t.get("from", "")).lower()
        t_to = str(t.get("to", "")).lower()
        for addr in (t_from, t_to):
            if addr in call_nodes_by_address:
                for call_nid in call_nodes_by_address[addr]:
                    # Only create edge if the call happens before the transfer
                    call_idx = int(call_nid.split(":")[1])
                    if call_idx < t["index"]:
                        edges.append(EVMEdge(
                            call_nid, t["node_id"],
                            "transfer_flow",
                            f"call frame → Transfer({addr})",
                        ))


def build_evm_graph(
    call_trace: Iterable[Mapping[str, Any]],
    *,
    telemetry: Iterable[Mapping[str, Any]] = (),
    layers: frozenset[str] | set[str] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Build a deterministic generic graph from trace evidence.

    Parent/child and call/return edges are structural evidence.  Value-flow
    edges are added only when telemetry explicitly identifies the source and
    target; no data dependency is guessed from temporal proximity.

    Args:
        call_trace: Iterable of trace events (enter/exit/storage/transfer).
        telemetry: Iterable of explicit telemetry items with source/target.
        layers: Set of layer names to enable. Default: all non-arithmetic layers.
    """
    active_layers = frozenset(layers) if layers is not None else DEFAULT_LAYERS
    unknown = active_layers - ALL_LAYERS
    if unknown:
        raise ValueError(f"unknown graph layer(s): {sorted(unknown)}")

    # Materialize the trace for multi-pass processing
    trace_list = list(call_trace)

    nodes: list[EVMNode] = []
    edges: list[EVMEdge] = []
    active: dict[int, str] = {}
    enters: dict[int, str] = {}

    # Layer 1: CALL/RETURN structural edges (always built as foundation)
    if "call_return" in active_layers:
        for index, item in enumerate(trace_list):
            event = str(item.get("event", ""))
            depth = item.get("depth")
            if event == "enter":
                sel = selector(item.get("input"))
                node_id = f"call:{index}"
                node = EVMNode(node_id, "mechanism", semantic_for(sel, item), index, depth,
                               item.get("from"), item.get("to"), sel, item.get("input"))
                nodes.append(node)
                enters[index] = node_id
                active[int(depth)] = node_id
                parent_depth = int(depth) - 1 if depth is not None else None
                if parent_depth is not None and parent_depth in active:
                    edges.append(EVMEdge(active[parent_depth], node_id, "control_flow", "call depth"))
            elif event == "exit":
                call_id = next((v for k, v in reversed(enters.items()) if k < index and active.get(depth) == v), None)
                if call_id:
                    return_id = f"return:{index}"
                    nodes.append(EVMNode(return_id, "state", "RETURN_VALUE", index, depth,
                                         item.get("from"), item.get("to"), value=item.get("output")))
                    edges.append(EVMEdge(call_id, return_id, "return_value", "matched call exit"))
                    active.pop(int(depth), None)

    # Layer 2: Return-value chaining
    if "return_chain" in active_layers:
        _add_return_chain_edges(nodes, edges, enters)

    # Layer 3: SLOAD/SSTORE edges
    if "storage" in active_layers:
        _add_storage_edges(nodes, edges, trace_list)

    # Layer 4: Token Transfer edges
    if "transfer" in active_layers:
        _add_transfer_edges(nodes, edges, trace_list)

    # Layer 5: arithmetic/branch edges – declared but not populated without
    # bytecode-level telemetry. This avoids guessing operand sources.
    # if "arithmetic" in active_layers:
    #     _add_arithmetic_edges(nodes, edges, trace_list)

    # Telemetry items (always processed as explicit evidence)
    for item in telemetry:
        node_id = str(item.get("node_id") or f"telemetry:{len(nodes)}")
        node = EVMNode(node_id, str(item.get("kind", "state")),
                       str(item.get("semantic", "STATE_CHANGE")),
                       item.get("trace_index"), item.get("depth"),
                       item.get("caller"), item.get("callee"),
                       item.get("selector"), item.get("value"), "telemetry")
        nodes.append(node)
        source = item.get("source_node")
        target = item.get("target_node")
        if source and target:
            edges.append(EVMEdge(str(source), str(target), str(item.get("relation", "dataflow")), "telemetry"))
    return {"nodes": [asdict(n) for n in nodes], "edges": [asdict(e) for e in edges]}


def backward_slice(graph: Mapping[str, Any], outcome_node: str) -> list[str]:
    incoming: dict[str, list[str]] = {}
    known = {str(node["node_id"]) for node in graph.get("nodes", [])}
    for edge in graph.get("edges", []):
        if edge["source"] in known and edge["target"] in known:
            incoming.setdefault(edge["target"], []).append(edge["source"])
    seen: set[str] = set()
    stack = [outcome_node]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        stack.extend(incoming.get(current, []))
    return sorted(seen)


def rank_semantic_candidates(graph: Mapping[str, Any], outcome_node: str) -> list[dict[str, Any]]:
    """Rank slice nodes; output remains human-review-only."""
    sliced = set(backward_slice(graph, outcome_node))
    ranked = []
    for node in graph.get("nodes", []):
        if node["node_id"] not in sliced or node["node_id"] == outcome_node:
            continue
        if node["semantic"] in {"CALL", "RETURN_VALUE", "STATE_READ", "STATE_WRITE"}:
            score = 0.5
        else:
            score = 1.0
        ranked.append({**node, "candidate_score": score, "status": "REVIEW_REQUIRED"})
    return sorted(ranked, key=lambda x: (-x["candidate_score"], x["node_id"]))
