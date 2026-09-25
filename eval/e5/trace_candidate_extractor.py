"""Extract candidate nodes directly from authenticated B2 call traces.

This module intentionally extracts structural CALL/STATICCALL evidence only.
It does not infer protocol business semantics or read hidden references.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from eval.e5.evm_causal_graph import semantic_for


def _selector(input_data: Any) -> str | None:
    if not isinstance(input_data, str) or not input_data.startswith("0x"):
        return None
    return input_data[:10].lower() if len(input_data) >= 10 else None


def extract_b2_call_nodes(path: Path, *, include_logs: bool = True) -> list[dict[str, Any]]:
    data = json.loads(path.read_text())
    traces = [tx.get("call_trace", []) for tx in data.get("per_tx", []) if tx.get("call_trace")]
    if not traces:
        return []
    trace = traces[-1]
    nodes = []
    for index, item in enumerate(trace):
        if item.get("event") != "enter" or item.get("type") not in {"CALL", "STATICCALL", "DELEGATECALL", "CALLCODE"}:
            continue
        sel = _selector(item.get("input"))
        semantic = semantic_for(sel, item)
        node_type = {
            "AUTH_CHECK": "auth_check",
            "PRICE_READ": "oracle_read",
            "BORROW": "flashloan_capital",
            "MINT": "mint",
            "ASSET_TRANSFER": "balance_update",
        }.get(semantic, "call_boundary")
        nodes.append({
            "id": f"trace_call@{index}",
            "trace_index": index,
            "semantic": semantic,
            "type": node_type,
            "selector": sel,
            "caller": item.get("from"),
            "callee": item.get("to"),
            "depth": item.get("depth"),
            "source": str(path),
            "provenance": "authenticated_b2_call_trace",
        })
    if include_logs:
        tx = next(tx for tx in data.get("per_tx", []) if tx.get("call_trace") is trace)
        for log_index, log in enumerate(tx.get("logs", [])):
            nodes.append({
                "id": f"transfer_log@{log_index}",
                "trace_index": None,
                "semantic": "ASSET_TRANSFER",
                "type": "asset_transfer",
                "address": log.get("address"),
                "topics": log.get("topics"),
                "source": str(path),
                "provenance": "authenticated_b2_transfer_log",
            })
    return nodes
