"""Tests for the five candidate reduction filters."""
from eval.e5.candidate_filter import (
    FilterResult,
    apply_filter_pipeline,
    filter_call_frame_lineage,
    filter_caller_callee_dedup,
    filter_semantic_compatibility,
    filter_telemetry_dataflow,
    filter_temporal_direction,
)


# ── helpers ──────────────────────────────────────────────────────────

def _cand(trace_index, group_id=None, ctype="oracle_read", cid=None):
    c = {"id": cid or f"g{group_id or 0}@{trace_index}", "trace_index": trace_index, "type": ctype}
    if group_id is not None:
        c["group_id"] = group_id
    return c


# ── Filter 1: Temporal direction ─────────────────────────────────────

def test_temporal_keeps_at_or_before_harm():
    candidates = [_cand(10), _cand(50), _cand(70), _cand(80)]
    r = filter_temporal_direction(candidates, harm_trace_index=70)
    assert r.output_count == 3  # 10, 50, and 70 (at harm) are kept
    assert all(c["trace_index"] <= 70 for c in r.kept)
    assert r.reduction_ratio > 0


def test_temporal_skips_when_no_harm_index():
    candidates = [_cand(10)]
    r = filter_temporal_direction(candidates, harm_trace_index=None)
    assert r.output_count == 1
    assert "skipped" in r.reason


# ── Filter 2: Call-frame lineage ─────────────────────────────────────

def test_lineage_filters_unrelated_subtree():
    # Simple call tree: root(0) -> child_a(1) -> harm(3), root(0) -> child_b(2)
    trace = [
        {"event": "enter", "trace_index": 0, "depth": 0},
        {"event": "enter", "trace_index": 1, "depth": 1},
        {"event": "enter", "trace_index": 3, "depth": 2},  # harm path
        {"event": "enter", "trace_index": 2, "depth": 1},  # unrelated subtree
    ]
    candidates = [_cand(0, cid="root"), _cand(1, cid="child_a"), _cand(2, cid="child_b")]
    r = filter_call_frame_lineage(candidates, harm_trace_index=3, call_trace=trace)
    kept_ids = {c["id"] for c in r.kept}
    # root(0) and child_a(1) are on the harm path; child_b(2) is sibling of child_a
    # under the conservative rule (ancestor + direct children of ancestors)
    assert "root" in kept_ids
    assert "child_a" in kept_ids


def test_lineage_passes_analyst_injected_nodes():
    trace = [{"event": "enter", "trace_index": 0, "depth": 0}]
    candidates = [{"id": "analyst_node", "trace_index": None, "type": "arithmetic"}]
    r = filter_call_frame_lineage(candidates, harm_trace_index=0, call_trace=trace)
    assert r.output_count == 1  # analyst node passes through


def test_lineage_skips_without_trace():
    candidates = [_cand(5)]
    r = filter_call_frame_lineage(candidates, harm_trace_index=10, call_trace=None)
    assert r.output_count == 1
    assert "skipped" in r.reason


# ── Filter 3: Semantic compatibility ─────────────────────────────────

def test_semantic_keeps_compatible_types():
    candidates = [
        _cand(10, ctype="oracle_read"),
        _cand(20, ctype="auth_check"),
        _cand(30, ctype="flashloan_capital"),
    ]
    r = filter_semantic_compatibility(candidates, harm_semantic="ASSET_TRANSFER")
    assert r.output_count == 3  # all are compatible with ASSET_TRANSFER


def test_semantic_filters_incompatible_nav():
    candidates = [
        _cand(10, ctype="oracle_read"),      # compatible with NAV
        _cand(20, ctype="flashloan_capital"), # NOT compatible with NAV
    ]
    r = filter_semantic_compatibility(candidates, harm_semantic="NAV_OBSERVATION")
    assert r.output_count == 1
    assert r.kept[0]["type"] == "oracle_read"


def test_semantic_skips_unknown_harm():
    candidates = [_cand(10)]
    r = filter_semantic_compatibility(candidates, harm_semantic="UNKNOWN_TYPE")
    assert r.output_count == 1
    assert "skipped" in r.reason


# ── Filter 4: Caller/callee dedup ────────────────────────────────────

def test_dedup_keeps_closest_to_harm():
    candidates = [
        _cand(10, group_id="g1"), _cand(30, group_id="g1"),
        _cand(50, group_id="g1"), _cand(60, group_id="g1"),
    ]
    r = filter_caller_callee_dedup(candidates, harm_trace_index=70)
    assert r.output_count == 1
    assert r.kept[0]["trace_index"] == 60  # closest before harm


def test_dedup_preserves_ungrouped():
    candidates = [
        _cand(10, cid="analyst_node"),  # no group_id
        _cand(20, group_id="g1"),
    ]
    r = filter_caller_callee_dedup(candidates, harm_trace_index=30)
    assert r.output_count == 2


def test_dedup_single_member_groups_unchanged():
    candidates = [_cand(10, group_id="g1"), _cand(20, group_id="g2")]
    r = filter_caller_callee_dedup(candidates, harm_trace_index=30)
    assert r.output_count == 2
    assert len(r.removed) == 0


# ── Filter 5: Telemetry dataflow ─────────────────────────────────────

def test_telemetry_annotates_connected():
    candidates = [_cand(10, cid="node_a"), _cand(20, cid="node_b")]
    edges = [{"source": "node_a", "target": "harm"}]
    r = filter_telemetry_dataflow(candidates, telemetry_edges=edges)
    assert r.output_count == 2  # non-destructive
    statuses = {c["id"]: c["telemetry_status"] for c in r.kept}
    assert statuses["node_a"] == "DATAFLOW_CONNECTED"
    assert statuses["node_b"] == "STRUCTURAL_ONLY"


def test_telemetry_no_edges_annotates_unavailable():
    candidates = [_cand(10, cid="node_a")]
    r = filter_telemetry_dataflow(candidates, telemetry_edges=None)
    assert r.kept[0]["telemetry_status"] == "NO_TELEMETRY_AVAILABLE"


# ── Pipeline ─────────────────────────────────────────────────────────

def test_pipeline_reduces_and_is_auditable():
    candidates = [
        _cand(10, group_id="g1"),
        _cand(30, group_id="g1"),
        _cand(50, group_id="g1"),
        _cand(80, group_id="g1"),  # after harm
    ]
    result = apply_filter_pipeline(
        candidates,
        harm_trace_index=70,
        harm_semantic="ASSET_TRANSFER",
    )
    assert result["initial_count"] == 4
    assert result["final_count"] < 4
    assert result["reduction_ratio"] > 0
    assert len(result["pipeline"]) == 5
    # No candidate after harm should survive
    for c in result["candidates"]:
        assert c["trace_index"] < 70


def test_pipeline_with_empty_candidates():
    result = apply_filter_pipeline([], harm_trace_index=10)
    assert result["final_count"] == 0
    assert result["reduction_ratio"] == 0.0
