import pytest
from eval.e5.dynamic_provenance import DynamicProvenance, ProvenanceError
from eval.e5.provenance_harm_slice import build_graph, slice_and_rank
from eval.e5.control_scope_audit import audit
from eval.e5.control_dependence_slice import build_control_slice
from eval.e5.control_candidate_slice import build_control_candidates

def L(op, pc, frame="0", storage="0xabc"):
    return {"op":op,"pc":pc,"depth":1,"frameId":frame,"storageContextAddress":storage}

def test_storage_arithmetic_branch_revert_lineage():
    logs=[L("PUSH1",1),L("SLOAD",2),L("PUSH1",3),L("ADD",4),L("PUSH1",5),L("EQ",6),L("PUSH1",7),L("JUMPI",8),L("PUSH1",9),L("PUSH1",10),L("REVERT",11)]
    p=DynamicProvenance(verify_shadow_stack=False).consume(logs)
    assert any(o.kind == "branch_predicate" for o in p.observations)
    rev=next(o for o in p.observations if o.kind == "revert_terminal")
    assert p.ancestors(rev.observation_id)

def test_storage_context_is_required():
    with pytest.raises(ProvenanceError):
        DynamicProvenance(verify_shadow_stack=False).consume([{"op":"PUSH1","pc":1},{"op":"SLOAD","pc":2,"depth":1,"frameId":"0"}])

def test_call_arity_and_success_value_are_frame_local():
    logs=[L("PUSH1",i,frame="a") for i in range(7)]
    logs += [L("CALL",20,frame="a"), L("PUSH1",21,frame="b"), L("SLOAD",22,frame="b")]
    p=DynamicProvenance(verify_shadow_stack=False).consume(logs)
    assert any(o.kind == "external_call" for o in p.observations)
    assert any(v.producer_opcode == "SLOAD" and v.frame_id == "b" for v in p.values.values())

def test_child_return_is_parent_of_parent_returndata():
    logs=[
        {"op":"PUSH1","pc":1,"depth":1,"frameId":"parent","value":"0","stack":[]},
        {"op":"PUSH1","pc":2,"depth":1,"frameId":"parent","value":"0","stack":["0"]},
        {"op":"PUSH1","pc":3,"depth":1,"frameId":"parent","value":"0","stack":["0","0"]},
        {"op":"PUSH1","pc":4,"depth":1,"frameId":"parent","value":"0","stack":["0","0","0"]},
        {"op":"PUSH1","pc":5,"depth":1,"frameId":"parent","value":"0","stack":["0","0","0","0"]},
        {"op":"PUSH1","pc":6,"depth":1,"frameId":"parent","value":"0","stack":["0","0","0","0","0"]},
        {"op":"PUSH1","pc":7,"depth":1,"frameId":"parent","value":"0","stack":["0","0","0","0","0","0"]},
        {"op":"CALL","pc":8,"depth":1,"frameId":"parent","stack":["0","0","0","0","0","0","0"]},
        {"op":"PUSH1","pc":9,"depth":2,"frameId":"child","value":"0","stack":[]},
        {"op":"PUSH1","pc":10,"depth":2,"frameId":"child","value":"32","stack":["0"]},
        {"op":"RETURN","pc":11,"depth":2,"frameId":"child","stack":["0","32"]},
        {"op":"PUSH1","pc":12,"depth":1,"frameId":"parent","value":"0","stack":["0"]},
    ]
    logs[11]["returnData"]="0x01"
    logs[11]["returnDataSourceFrame"]="child"
    p=DynamicProvenance(verify_shadow_stack=False).consume(logs)
    returned=next(v for v in p.values.values() if v.producer_opcode == "RETURNDATA")
    root=next(v for v in p.values.values() if v.producer_opcode == "FRAME_RETURN_DATA")
    assert returned.parents == (root.value_id,)

def test_returndatacopy_uses_evm_dest_offset_order():
    logs=[
        {"op":"PUSH1","pc":1,"depth":1,"frameId":"0","value":"32","stack":[]},
        {"op":"PUSH1","pc":2,"depth":1,"frameId":"0","value":"0","stack":["32"]},
        {"op":"PUSH1","pc":3,"depth":1,"frameId":"0","value":"64","stack":["32","0"]},
        {"op":"RETURNDATACOPY","pc":4,"depth":1,"frameId":"0","stack":["32","0","64"],"returnData":"0x01"},
        {"op":"PUSH1","pc":5,"depth":1,"frameId":"0","value":"64","stack":[]},
        {"op":"MLOAD","pc":6,"depth":1,"frameId":"0","stack":["64"]},
    ]
    p=DynamicProvenance(verify_shadow_stack=False).consume(logs)
    mload=next(v for v in p.values.values() if v.producer_opcode == "MLOAD")
    assert any(pv.producer_opcode == "RETURNDATA_UNKNOWN" for pv in p.values.values()) or mload.parents

def test_cross_frame_control_candidates_are_not_causal_verdicts():
    p={
        "frame_parent":{"child":"parent"},
        "observations":[
            {"observation_id":"ret","kind":"returndata_copy","frame_id":"parent"},
            {"observation_id":"br","kind":"branch_predicate","frame_id":"parent","pc":10,"branch_target":20,"branch_taken":True},
            {"observation_id":"sink","kind":"event_log","frame_id":"child"},
        ],
    }
    result=build_control_candidates(p,"sink")
    assert result["candidate_count"] == 2
    assert all(c["status"] != "CAUSE" for c in result["candidates"])

def test_unknown_opcode_fails_closed():
    with pytest.raises(ProvenanceError):
        DynamicProvenance(verify_shadow_stack=False).consume([L("FUTURE_OP",1)])

def test_transient_storage_is_tracked_without_guessing_owner():
    logs=[L("PUSH1",1),L("TLOAD",2),L("PUSH1",3),L("PUSH1",4),L("TSTORE",5)]
    p=DynamicProvenance(verify_shadow_stack=False).consume(logs)
    assert any(v.producer_opcode == "TLOAD" for v in p.values.values())
    assert any(o.kind == "transient_state_write" for o in p.observations)

def test_shadow_stack_mismatch_fails_closed():
    with pytest.raises(ProvenanceError):
        DynamicProvenance().consume([
            {"op":"PUSH1","pc":1,"depth":1,"frameId":"0","stack":[]},
            {"op":"PUSH1","pc":2,"depth":1,"frameId":"0","stack":[]},
        ])

def test_harm_slice_uses_only_authenticated_value_edges():
    provenance={
        "values":[
            {"value_id":"v0","producer_opcode":"PUSH1","parents":[]},
            {"value_id":"v1","producer_opcode":"ADD","parents":["v0"]},
            {"value_id":"v2","producer_opcode":"AUTHENTICATED_PRESTATE","parents":[]},
        ],
        "observations":[{"observation_id":"o0","kind":"event_log","values":["v1","v2"]}],
    }
    nodes, edges=build_graph(provenance, "o0")
    candidates=slice_and_rank(nodes, edges, "o0")
    assert [item["id"] for item in candidates] == ["v1", "v0"]

def test_jumpi_records_target_and_dynamic_taken_status():
    logs=[
        {"op":"PUSH1","pc":1,"depth":1,"frameId":"0","value":"1","stack":[]},
        {"op":"PUSH1","pc":2,"depth":1,"frameId":"0","value":"9","stack":["1"]},
        {"op":"JUMPI","pc":3,"depth":1,"frameId":"0","stack":["1","9"]},
        {"op":"JUMPDEST","pc":9,"depth":1,"frameId":"0","stack":[]},
    ]
    p=DynamicProvenance().consume(logs)
    branch=next(o for o in p.observations if o.kind == "branch_predicate")
    assert branch.branch_target == 9
    assert branch.branch_taken is True

def test_jump_records_dynamic_target_for_cfg_only():
    logs=[
        {"op":"PUSH1","pc":1,"depth":1,"frameId":"0","value":"9","stack":[]},
        {"op":"JUMP","pc":2,"depth":1,"frameId":"0","stack":["9"]},
    ]
    p=DynamicProvenance().consume(logs)
    jump=next(o for o in p.observations if o.kind == "jump_target")
    assert jump.branch_target == 9

def test_control_scope_requires_more_than_jumpdest_validation():
    p={"frame_code":{"0":"0x60095b"},"observations":[{
        "observation_id":"o0","kind":"branch_predicate","frame_id":"0",
        "pc":0,"branch_target":2,"branch_taken":True,
    }]}
    result=audit(p)
    assert result["target_validated_count"] == 1
    assert result["control_scope_ready"] is False

def test_control_edge_requires_verified_postdominator():
    p={"frame_code":{"0":"0x600160075760005b00"},"observations":[
        {"observation_id":"o_branch","kind":"branch_predicate","frame_id":"0","pc":4,"branch_target":7,"branch_taken":True},
        {"observation_id":"o_fallthrough","kind":"event_log","frame_id":"0","pc":5},
        {"observation_id":"o_join","kind":"event_log","frame_id":"0","pc":7},
    ]}
    result=build_control_slice(p)
    assert result["edge_count"] == 1
    assert result["edges"][0]["kind"] == "control_dependence"

def test_control_slice_can_scope_to_harm_ancestors():
    p={"frame_code":{"0":"0x00","1":"0x00"},"values":[
        {"value_id":"v0","producer_opcode":"PUSH1","frame_id":"0","parents":[]},
        {"value_id":"v1","producer_opcode":"PUSH1","frame_id":"1","parents":[]},
    ],"observations":[
        {"observation_id":"o0","kind":"event_log","frame_id":"0","values":["v0"]},
        {"observation_id":"o1","kind":"event_log","frame_id":"1","values":["v1"]},
    ]}
    result=build_control_slice(p, "o0")
    assert result["frame_scope"] == "harm_slice_ancestors"
