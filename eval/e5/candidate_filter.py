"""Deterministic candidate reduction filters for E5 causal ranking.

Each filter is independently testable and returns an auditable record of
what was kept, what was removed, and why.  Filters are composed in a
pipeline; each stage only sees the output of the previous stage.

Filters never promote a candidate to CAUSE; they only reduce the review
set with provenance-justified reasons.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class FilterResult:
    """Auditable record of a single filter application."""
    filter_name: str
    input_count: int
    kept: list[dict[str, Any]]
    removed: list[dict[str, Any]]
    reason: str

    @property
    def output_count(self) -> int:
        return len(self.kept)

    @property
    def reduction_ratio(self) -> float:
        return 1.0 - (self.output_count / self.input_count) if self.input_count else 0.0


# ---------------------------------------------------------------------------
# Filter 1: Temporal direction
# ---------------------------------------------------------------------------

def filter_temporal_direction(
    candidates: list[dict[str, Any]],
    harm_trace_index: int | None,
) -> FilterResult:
    """Keep candidates whose trace_index is at or before the harm node.

    Rationale: a cause must precede or coincide with its effect in the
    execution trace.  A mechanism at the same trace index as harm (e.g.,
    an accounting conversion that IS the harm observation) is kept.
    Candidates strictly after the harm point are excluded.
    """
    if harm_trace_index is None:
        return FilterResult("temporal_direction", len(candidates), list(candidates), [], "harm_trace_index missing; filter skipped")
    kept, removed = [], []
    for c in candidates:
        idx = c.get("trace_index")
        if isinstance(idx, int) and idx <= harm_trace_index:
            kept.append(c)
        else:
            removed.append(c)
    return FilterResult("temporal_direction", len(candidates), kept, removed,
                        f"kept {len(kept)} candidates at or before harm@{harm_trace_index}")


# ---------------------------------------------------------------------------
# Filter 2: Call-frame lineage
# ---------------------------------------------------------------------------

def _build_call_tree(trace: list[dict[str, Any]]) -> dict[int, list[int]]:
    """Build parent→children map from enter events using depth."""
    children: dict[int, list[int]] = {}
    active_at_depth: dict[int, int] = {}
    for item in trace:
        if item.get("event") != "enter":
            continue
        idx = item.get("trace_index")
        depth = item.get("depth")
        if idx is None or depth is None:
            continue
        idx, depth = int(idx), int(depth)
        parent_depth = depth - 1
        if parent_depth in active_at_depth:
            parent_idx = active_at_depth[parent_depth]
            children.setdefault(parent_idx, []).append(idx)
        children.setdefault(idx, [])
        active_at_depth[depth] = idx
    return children


def _ancestors_of(target: int, children: dict[int, list[int]]) -> set[int]:
    """Find all ancestor trace indices of target in the call tree."""
    # Build reverse map
    parent_of: dict[int, int] = {}
    for p, kids in children.items():
        for k in kids:
            parent_of[k] = p
    ancestors: set[int] = set()
    current = target
    while current in parent_of:
        current = parent_of[current]
        ancestors.add(current)
    return ancestors


def filter_call_frame_lineage(
    candidates: list[dict[str, Any]],
    harm_trace_index: int | None,
    call_trace: list[dict[str, Any]] | None = None,
) -> FilterResult:
    """Keep candidates on an ancestor path from root to harm in the call tree.

    Candidates in unrelated call subtrees are removed because there is no
    control-flow dependency between them and the harm event.
    """
    if harm_trace_index is None or not call_trace:
        return FilterResult("call_frame_lineage", len(candidates), list(candidates), [],
                            "call_trace or harm_trace_index missing; filter skipped")

    indexed_trace = []
    for i, item in enumerate(call_trace):
        entry = dict(item)
        entry.setdefault("trace_index", i)
        indexed_trace.append(entry)

    children = _build_call_tree(indexed_trace)
    harm_ancestors = _ancestors_of(harm_trace_index, children)
    # The harm node itself and its ancestors are on the lineage path
    lineage = harm_ancestors | {harm_trace_index}

    # Also include descendants of harm ancestors (siblings may be relevant
    # if they share the same parent context)
    # Actually, be conservative: only ancestor path + direct children of ancestors
    relevant = set(lineage)
    for ancestor in harm_ancestors:
        for child in children.get(ancestor, []):
            relevant.add(child)

    kept, removed = [], []
    for c in candidates:
        idx = c.get("trace_index")
        if isinstance(idx, int) and idx in relevant:
            kept.append(c)
        elif not isinstance(idx, int):
            # Non-trace nodes (analyst-injected) pass through
            kept.append(c)
        else:
            removed.append(c)
    return FilterResult("call_frame_lineage", len(candidates), kept, removed,
                        f"kept {len(kept)} candidates on harm ancestor path ({len(lineage)} lineage nodes)")


# ---------------------------------------------------------------------------
# Filter 3: Semantic compatibility
# ---------------------------------------------------------------------------

# Maps harm semantic → compatible candidate types
SEMANTIC_COMPATIBILITY: dict[str, set[str]] = {
    "ASSET_TRANSFER": {"auth_check", "accounting_conversion", "arithmetic", "call_boundary",
                       "oracle_read", "amm_reserve_read", "flashloan_capital",
                       "enabling_path", "balance_update", "mint"},
    "NAV_OBSERVATION": {"oracle_read", "accounting_conversion", "amm_reserve_read", "call_boundary",
                        "arithmetic", "enabling_path"},
    "STATE_WRITE": {"oracle_read", "amm_reserve_read", "arithmetic", "call_boundary",
                    "accounting_conversion", "auth_check"},
}


def filter_semantic_compatibility(
    candidates: list[dict[str, Any]],
    harm_semantic: str | None,
) -> FilterResult:
    """Keep candidates whose type is semantically compatible with the harm.

    If no compatibility rule exists for the harm semantic, all candidates pass.
    """
    if not harm_semantic or harm_semantic not in SEMANTIC_COMPATIBILITY:
        return FilterResult("semantic_compatibility", len(candidates), list(candidates), [],
                            f"no compatibility rule for harm semantic '{harm_semantic}'; filter skipped")
    compatible = SEMANTIC_COMPATIBILITY[harm_semantic]
    kept, removed = [], []
    for c in candidates:
        ctype = c.get("type", "")
        if ctype in compatible or not ctype:
            kept.append(c)
        else:
            removed.append(c)
    return FilterResult("semantic_compatibility", len(candidates), kept, removed,
                        f"kept {len(kept)} candidates compatible with {harm_semantic}")


# ---------------------------------------------------------------------------
# Filter 4: Caller/callee boundary dedup
# ---------------------------------------------------------------------------

def filter_caller_callee_dedup(
    candidates: list[dict[str, Any]],
    harm_trace_index: int | None,
) -> FilterResult:
    """Deduplicate repeated calls to the same callee at the same depth.

    When multiple occurrences of the same (group_id) exist, keep only the one
    closest to the harm point.  This reduces repeated oracle reads to the most
    relevant invocation.
    """
    if harm_trace_index is None:
        return FilterResult("caller_callee_dedup", len(candidates), list(candidates), [],
                            "harm_trace_index missing; filter skipped")

    # Group by group_id (if present)
    groups: dict[str, list[dict[str, Any]]] = {}
    ungrouped: list[dict[str, Any]] = []
    for c in candidates:
        gid = c.get("group_id")
        if gid:
            groups.setdefault(gid, []).append(c)
        else:
            ungrouped.append(c)

    kept: list[dict[str, Any]] = list(ungrouped)
    removed: list[dict[str, Any]] = []

    for gid, members in groups.items():
        if len(members) <= 1:
            kept.extend(members)
            continue
        # Keep the member closest to harm (but before it, if possible)
        before = [m for m in members if isinstance(m.get("trace_index"), int) and m["trace_index"] < harm_trace_index]
        if before:
            best = max(before, key=lambda m: m["trace_index"])
        else:
            best = min(members, key=lambda m: abs((m.get("trace_index") or 0) - harm_trace_index))
        for m in members:
            if m is best:
                kept.append(m)
            else:
                removed.append(m)

    return FilterResult("caller_callee_dedup", len(candidates), kept, removed,
                        f"deduped {len(removed)} repeated group occurrences")


# ---------------------------------------------------------------------------
# Filter 5: Telemetry dataflow annotation
# ---------------------------------------------------------------------------

def filter_telemetry_dataflow(
    candidates: list[dict[str, Any]],
    telemetry_edges: list[dict[str, Any]] | None = None,
) -> FilterResult:
    """Annotate candidates with telemetry connectivity status.

    Unlike other filters, this one does NOT remove candidates; it adds a
    `telemetry_status` field: `DATAFLOW_CONNECTED` if there is an explicit
    telemetry edge linking this candidate to the harm path, otherwise
    `STRUCTURAL_ONLY`.  Candidates with dataflow evidence get a score boost.

    This is an annotation filter: all candidates pass through.
    """
    if not telemetry_edges:
        for c in candidates:
            c["telemetry_status"] = "NO_TELEMETRY_AVAILABLE"
        return FilterResult("telemetry_dataflow", len(candidates), list(candidates), [],
                            "no telemetry edges provided; all candidates annotated NO_TELEMETRY_AVAILABLE")

    # Build set of node IDs with telemetry connections
    connected: set[str] = set()
    for edge in telemetry_edges:
        connected.add(str(edge.get("source", "")))
        connected.add(str(edge.get("target", "")))

    for c in candidates:
        node_id = c.get("id", "")
        if node_id in connected:
            c["telemetry_status"] = "DATAFLOW_CONNECTED"
        else:
            c["telemetry_status"] = "STRUCTURAL_ONLY"

    return FilterResult("telemetry_dataflow", len(candidates), list(candidates), [],
                        f"{sum(1 for c in candidates if c.get('telemetry_status') == 'DATAFLOW_CONNECTED')} candidates with dataflow evidence")


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def apply_filter_pipeline(
    candidates: list[dict[str, Any]],
    *,
    harm_trace_index: int | None = None,
    harm_semantic: str | None = None,
    call_trace: list[dict[str, Any]] | None = None,
    telemetry_edges: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Apply all five filters in sequence and return auditable results."""
    pipeline_results: list[dict[str, Any]] = []
    current = list(candidates)
    initial_count = len(current)

    # 1. Temporal direction
    r1 = filter_temporal_direction(current, harm_trace_index)
    pipeline_results.append({"filter": r1.filter_name, "input": r1.input_count,
                             "output": r1.output_count, "removed": len(r1.removed),
                             "reason": r1.reason})
    current = r1.kept

    # 2. Call-frame lineage
    r2 = filter_call_frame_lineage(current, harm_trace_index, call_trace)
    pipeline_results.append({"filter": r2.filter_name, "input": r2.input_count,
                             "output": r2.output_count, "removed": len(r2.removed),
                             "reason": r2.reason})
    current = r2.kept

    # 3. Semantic compatibility
    r3 = filter_semantic_compatibility(current, harm_semantic)
    pipeline_results.append({"filter": r3.filter_name, "input": r3.input_count,
                             "output": r3.output_count, "removed": len(r3.removed),
                             "reason": r3.reason})
    current = r3.kept

    # 4. Caller/callee dedup
    r4 = filter_caller_callee_dedup(current, harm_trace_index)
    pipeline_results.append({"filter": r4.filter_name, "input": r4.input_count,
                             "output": r4.output_count, "removed": len(r4.removed),
                             "reason": r4.reason})
    current = r4.kept

    # 5. Telemetry annotation (non-destructive)
    r5 = filter_telemetry_dataflow(current, telemetry_edges)
    pipeline_results.append({"filter": r5.filter_name, "input": r5.input_count,
                             "output": r5.output_count, "removed": len(r5.removed),
                             "reason": r5.reason})
    current = r5.kept

    final_count = len(current)
    return {
        "initial_count": initial_count,
        "final_count": final_count,
        "reduction_ratio": round(1.0 - (final_count / initial_count), 6) if initial_count else 0.0,
        "pipeline": pipeline_results,
        "candidates": current,
    }
