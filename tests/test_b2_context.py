import hashlib
import json

from core.rpc import RpcError
from eval.results.b2_context import acquire
from eval.results.b2_context import _validate_ancestor_headers
from eval.b2_proofs import BEACON_ROOTS_ADDRESS, _canonical_storage_key


def _header(number: int, block_hash: str, parent_hash: str) -> dict:
    return {
        "number": hex(number),
        "hash": block_hash,
        "parentHash": parent_hash,
    }


def test_ancestor_validation_accepts_target_parent_chain():
    oldest = _header(8, "0x08", "0x07")
    parent = _header(9, "0x09", "0x08")
    block = _header(10, "0x10", "0x09")

    _validate_ancestor_headers(block, [parent, oldest])


def test_ancestor_validation_rejects_disconnected_chain():
    parent = _header(9, "0x09", "0x08")
    wrong_oldest = _header(8, "0x88", "0x07")
    block = _header(10, "0x10", "0x09")

    try:
        _validate_ancestor_headers(block, [parent, wrong_oldest])
    except RpcError as exc:
        assert "contiguous" in str(exc)
    else:
        raise AssertionError("disconnected ancestor chain was accepted")


def test_ancestor_validation_rejects_future_header():
    block = _header(10, "0x10", "0x11")
    future = _header(11, "0x11", "0x10")

    try:
        _validate_ancestor_headers(block, [future])
    except RpcError as exc:
        assert "before target" in str(exc)
    else:
        raise AssertionError("future ancestor was accepted")


def test_storage_keys_are_canonical_bytes32_for_eth_get_proof():
    assert _canonical_storage_key("0x685") == "0x" + "0" * 61 + "685"
    assert _canonical_storage_key("0x2684") == "0x" + "0" * 60 + "2684"
    assert _canonical_storage_key("0x" + "12" * 32) == "0x" + "12" * 32


def test_storage_key_rejects_invalid_or_out_of_range_values():
    import pytest

    with pytest.raises(ValueError):
        _canonical_storage_key("0xnot-hex")
    with pytest.raises(ValueError):
        _canonical_storage_key(1 << 256)


def test_beacon_roots_system_address_is_a_20_byte_address():
    assert len(BEACON_ROOTS_ADDRESS.removeprefix("0x")) == 40
    assert BEACON_ROOTS_ADDRESS == "0x000f3df6d732807ef1319fb7b8bb8522d0beac02"


def test_history_storage_uses_previous_block_ring_index():
    assert _canonical_storage_key((22781962 - 1) % 8191).endswith("0000000000000000000000000000000000000000000000000000000000000ae6")


class FakeContextRPC:
    url = "https://archive.example"
    last_endpoint = url

    def __init__(self, *, missing_post=False):
        self.missing_post = missing_post
        self.trace_calls = []

    def call(self, method, params):
        if method == "eth_getBlockByNumber":
            number = int(params[0], 16)
            if number == 3:
                return {"number": "0x3", "hash": "0xb3",
                        "parentHash": "0xb2", "transactions": [
                            {"hash": "0xtx"},
                        ]}
            return {"number": hex(number), "hash": f"0xb{number}",
                    "parentHash": f"0xb{number - 1}"}
        if method == "debug_traceTransaction":
            self.trace_calls.append(params[1])
            if params[1].get("tracerConfig", {}).get("diffMode"):
                return {"pre": {}} if self.missing_post else {"pre": {}, "post": {}}
            return {"0x01": {"storage": {}}}
        raise AssertionError(method)

    def eth_get_receipt(self, tx_hash):
        return {"status": "0x1", "gasUsed": "0x5208", "logs": []}


def test_context_acquisition_writes_poststate_and_manifest(tmp_path):
    archive = FakeContextRPC()
    result = acquire(archive, archive, tx_hash="0xtx", block_number=3,
                     tx_index=0, out=tmp_path / "context")
    context = tmp_path / "context"
    assert result["poststate_count"] == 1
    row = json.loads((context / "poststates.json").read_text())[0]
    assert row["prestate"] == {}
    assert row["poststate"] == {}
    manifest = json.loads((context / "manifest.json").read_text())
    assert manifest["ready_for_geth_runner"] is True
    for name, digest in manifest["input_hashes"].items():
        assert hashlib.sha256((context / name).read_bytes()).hexdigest() == digest


def test_context_acquisition_rejects_missing_diffmode_poststate(tmp_path):
    archive = FakeContextRPC(missing_post=True)
    result = acquire(archive, archive, tx_hash="0xtx", block_number=3,
                     tx_index=0, out=tmp_path / "context")
    assert result["ready_for_geth_runner"] is False
    assert result["failures"][0]["failure_class"] == "archive_trace_failure"
