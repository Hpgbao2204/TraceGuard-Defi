import pytest

from eval.b2_closure import _load_footprint, footprint_from_failures, footprint_id, run_closure


def test_footprint_parser_accepts_account_and_storage_failures():
    result = footprint_from_failures([
        "SLOAD:account:0x0000000000000000000000000000000000000001:slot:0x02",
        "SSTORE:dynamic-unproven-slot:0x0000000000000000000000000000000000000002:0x03",
        "SLOAD:dynamic-unproven-slot:0x0000000000000000000000000000000000000003:0x04",
        "SLOAD:account:0x0000000000000000000000000000000000000005",
        "CREATE2:destination-not-proof-bound:0x0000000000000000000000000000000000000006",
        "account:0x0000000000000000000000000000000000000004",
        "irrelevant:diagnostic",
    ])
    assert result == {
        "0x0000000000000000000000000000000000000001": {"0x02"},
        "0x0000000000000000000000000000000000000002": {"0x03"},
        "0x0000000000000000000000000000000000000003": {"0x04"},
        "0x0000000000000000000000000000000000000004": set(),
        "0x0000000000000000000000000000000000000005": set(),
        "0x0000000000000000000000000000000000000006": set(),
    }


def test_footprint_parser_ignores_unstructured_failures():
    assert footprint_from_failures([None, "SLOAD:short-stack", ""]) == {}


def test_footprint_parser_accepts_state_boundary_failure_details():
    assert footprint_from_failures([{
        "phase": "state-boundary", "method": "GetState",
        "storage_context_address": "0x0000000000000000000000000000000000000001",
        "slot": "0x02",
    }]) == {"0x0000000000000000000000000000000000000001": {"0x02"}}


def test_existing_footprint_is_loaded_for_resume(tmp_path):
    path = tmp_path / "footprint.json"
    path.write_text('{"0x01": ["0x02"]}\n')
    assert _load_footprint(path) == {"0x01": {"0x02"}}


def test_canonical_closure_refuses_hidden_resume(tmp_path):
    context = tmp_path / "context"
    context.mkdir()
    proofs = context / "prestate_proofs.json"
    proofs.write_text("{}\n")
    output = context / "evidence.json"
    output.with_name("evidence.footprint.json").write_text("{}\n")
    with pytest.raises(ValueError, match="resume-discovery"):
        run_closure(context, proofs, output, "https://archive.example",
                    target_index=0)


def test_footprint_id_binds_parent_header_state_root(tmp_path):
    context = tmp_path / "context"
    context.mkdir()
    (context / "block.json").write_text(
        '{"number":"0x10","parentHash":"0xparent","stateRoot":"0xchild"}\n'
    )
    (context / "ancestors.json").write_text(
        '[{"number":"0xf","hash":"0xparent","stateRoot":"0xparent-root"}]\n'
    )
    first = footprint_id(context, {"0x01": {"0x02"}}, chain_id=1, target_index=0)
    (context / "ancestors.json").write_text(
        '[{"number":"0xf","hash":"0xparent","stateRoot":"0xother-root"}]\n'
    )
    second = footprint_id(context, {"0x01": {"0x02"}}, chain_id=1, target_index=0)
    assert first != second


def test_state_boundary_failure_details_preserve_account_and_method():
    result = footprint_from_failures([{
        "phase": "state-boundary",
        "method": "GetBalance",
        "address": "0x0000000000000000000000000000000000000007",
    }])
    assert result == {"0x0000000000000000000000000000000000000007": set()}
