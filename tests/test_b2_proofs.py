import json
from pathlib import Path

import pytest

from core.rpc import RpcError
from eval.b2_proofs import (_accounts_from_traces, _validate_state_header_binding,
                             acquire)


class FakeArchive:
    url = "https://archive.example"
    last_endpoint = url

    def __init__(self, interrupt_after=None):
        self.calls = []
        self.interrupt_after = interrupt_after

    def call(self, method, params):
        if method == "eth_getBlockByNumber":
            return {"number": "0xf", "hash": "0x0f", "stateRoot": "0xroot"}
        if method == "eth_getCode":
            return "0x"
        if method != "eth_getProof":
            raise AssertionError(method)
        self.calls.append(params[0])
        if self.interrupt_after is not None and len(self.calls) > self.interrupt_after:
            raise KeyboardInterrupt()
        return {"address": params[0], "accountProof": [], "storageProof": []}


def _context(tmp_path: Path) -> Path:
    context = tmp_path / "context"
    context.mkdir()
    (context / "block.json").write_text(json.dumps({
        "number": "0x10", "parentHash": "0x0f",
    }))
    (context / "ancestors.json").write_text(json.dumps([{
        "number": "0xf", "hash": "0x0f", "stateRoot": "0xroot",
        "parentHash": "0x0e",
    }]))
    traces = [{"trace": {address: {"storage": {}}}}
              for address in ("0x02", "0x01", "0x03")]
    (context / "prestates.json").write_text(json.dumps(traces))
    (context / "transactions.json").write_text("[]")
    return context


def test_proof_acquisition_resumes_completed_chunk(tmp_path):
    context = _context(tmp_path)
    interrupted = FakeArchive(interrupt_after=2)
    with pytest.raises(KeyboardInterrupt):
        acquire(context, interrupted, chunk_size=2, chunk_attempts=1)

    progress = json.loads((context / "proof_progress.json").read_text())
    assert progress["proof_count"] == 2
    assert (context / "proof_chunks" / "chunk-00000.json").is_file()

    resumed = FakeArchive()
    result = acquire(context, resumed, chunk_size=2, chunk_attempts=1)
    assert result["prestate_proof_complete"] is True
    assert resumed.calls == ["0x03"]
    artifact = json.loads((context / "prestate_proofs.json").read_text())
    assert artifact["schema_version"] == 3
    proofs = artifact["proofs"]
    assert len(proofs) == 3
    assert all(item["code"] == "0x" for item in proofs)


def test_proof_header_must_match_canonical_parent():
    block = {"number": "0x10", "parentHash": "0x0f"}
    parent = {"number": "0xf", "hash": "0x0f", "stateRoot": "0xroot"}
    header = {"number": "0xf", "hash": "0xwrong", "stateRoot": "0xroot"}

    with pytest.raises(RpcError, match="canonical parent"):
        _validate_state_header_binding(block, header, [parent])


def test_proof_footprint_includes_accounts_from_diff_poststate():
    created = "0x0000000000000000000000000000000000000042"
    footprint = _accounts_from_traces(
        [{"trace": {"0x01": {"storage": {}}}}],
        [{"prestate": {}, "poststate": {created: {"storage": {"0x02": "0x01"}}}}],
    )
    assert created in footprint
    assert "0x" + "0" * 63 + "2" in footprint[created]


def test_proof_footprint_includes_geth_creation_destinations():
    created = "0x0000000000000000000000000000000000000043"
    footprint = _accounts_from_traces([], [{"calltrace": {
        "type": "CALL", "calls": [{"type": "CREATE2", "to": created}]
    }}])
    assert created in footprint


def test_extra_footprint_is_requested_without_replacing_discovered_accounts(tmp_path):
    context = _context(tmp_path)
    result = acquire(
        context,
        FakeArchive(),
        chunk_size=50,
        chunk_attempts=1,
        extra_footprint={"0x0000000000000000000000000000000000000004": {"0xabc"}},
    )
    assert result["prestate_proof_complete"] is True
    artifact = json.loads((context / "prestate_proofs.json").read_text())
    item = next(item for item in artifact["proofs"] if item["address"] == "0x0000000000000000000000000000000000000004")
    assert item["storage_keys"] == ["0x" + "0" * 61 + "abc"]
    assert len(artifact["proofs"]) == 4
