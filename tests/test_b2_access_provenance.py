from eval.b2_access_provenance import classify_failures, normalize_struct_logs, reconstruct_frame_ids


def test_standard_struct_logs_without_context_are_diagnostic_only():
    accesses, problems = normalize_struct_logs(
        {"structLogs": [{"pc": 7, "depth": 2, "op": "SLOAD", "stack": ["0x01"]}]},
        tx_index=3,
    )
    assert accesses == []
    assert "log-0:missing-storage-context-address" in problems


def test_custom_trace_normalizes_explicit_storage_context():
    accesses, problems = normalize_struct_logs(
        {"structLogs": [{"pc": 7, "depth": 2, "op": "SLOAD", "stack": ["0x01"],
                         "storageContextAddress": "0xAa"}]}, tx_index=3)
    assert not problems
    assert accesses[0]["storage_context_address"] == "0xaa"
    assert accesses[0]["storage_slot"] == "0x" + "01".zfill(64)


def test_frame_reconstruction_refuses_depth_only_alignment():
    logs = {"structLogs": [{"pc": 1, "depth": 1, "op": "SLOAD", "stack": ["0x01"]}]}
    frames = {"type": "CALL", "from": "0xaa", "to": "0xbb", "calls": []}
    mapping, problems = reconstruct_frame_ids(logs, frames)
    assert mapping == {}
    assert "log-0:missing-or-unknown-frame-id" in problems


def test_frame_reconstruction_preserves_explicit_frame_path():
    logs = {"structLogs": [{"pc": 1, "depth": 1, "op": "SLOAD", "stack": ["0x01"], "frameId": "0"}]}
    frames = {"type": "CALL", "from": "0xaa", "to": "0xbb"}
    mapping, problems = reconstruct_frame_ids(logs, frames)
    assert mapping == {0: "0"}
    assert problems == []


def test_matching_failure_is_deterministic_gap():
    failure = {"tx_index": 3, "pc": 7, "depth": 2, "opcode": "SLOAD",
               "storage_context_address": "0xaa", "slot": "0x" + "01".zfill(64)}
    canonical = [{"tx_index": 3, "pc": 7, "depth": 2, "opcode": "SLOAD",
                  "storage_context_address": "0xaa", "storage_slot": failure["slot"]}]
    assert classify_failures([failure], canonical)[0]["classification"] == "DETERMINISTIC_ACQUISITION_GAP"


def test_absent_failure_is_unresolved_without_path_evidence():
    failure = {"tx_index": 3, "pc": 8, "depth": 2, "opcode": "SLOAD",
               "storage_context_address": "0xaa", "slot": "0x02"}
    assert classify_failures([failure], [])[0]["classification"] == "UNRESOLVED_PROVENANCE"


def test_explicit_path_divergence_is_candidate():
    failure = {"tx_index": 3, "pc": 8, "depth": 2, "opcode": "SLOAD",
               "storage_context_address": "0xaa", "slot": "0x02", "path_diverged": True}
    assert classify_failures([failure], [])[0]["classification"] == "SEQUENTIAL_OR_PATH_DEPENDENT_CANDIDATE"
