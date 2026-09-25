"""Normalize canonical opcode traces for authenticated-read provenance audits.

This module deliberately does not infer storage ownership from a call target.
Standard ``structLogs`` do not identify the storage context for delegate calls,
so such traces are diagnostic-only unless an explicit context address is
provided by the trace producer.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


STORAGE_OPCODES = {"SLOAD", "SSTORE"}


@dataclass(frozen=True)
class Access:
    tx_index: int
    pc: int
    depth: int
    opcode: str
    storage_context_address: str
    storage_slot: str
    code_address: str | None = None
    frame_id: str | None = None

    def key(self) -> tuple[Any, ...]:
        return (self.tx_index, self.pc, self.depth, self.opcode,
                self.storage_context_address.lower(), self.storage_slot.lower())


def _hex(value: Any) -> str | None:
    if isinstance(value, str):
        value = value.lower()
        if value.startswith("0x"):
            return "0x" + value[2:].zfill(64)[-64:]
    if isinstance(value, int) and value >= 0:
        return f"0x{value:064x}"
    return None


def _flatten_frames(frame: Any, path: str = "0") -> list[dict[str, Any]]:
    if not isinstance(frame, dict):
        return []
    item = {"frame_id": path, "type": frame.get("type"),
            "from": frame.get("from"), "to": frame.get("to")}
    result = [item]
    calls = frame.get("calls")
    if isinstance(calls, list):
        for ordinal, child in enumerate(calls):
            result.extend(_flatten_frames(child, f"{path}.{ordinal}"))
    return result


def reconstruct_frame_ids(struct_logs: Any, call_trace: Any) -> tuple[dict[int, str], list[str]]:
    """Map explicit trace frame annotations to callTracer frame paths.

    Geth's standard structLogs do not expose call boundaries or storage
    context.  Consequently this function accepts only logs that carry an
    explicit ``frameId`` (provided by a trace adapter that has already
    validated alignment).  It refuses to guess from depth alone: sibling
    frames can share a depth and DELEGATECALL has different storage semantics.
    """
    frames = _flatten_frames(call_trace)
    known = {f["frame_id"] for f in frames}
    logs = struct_logs.get("structLogs") if isinstance(struct_logs, dict) else struct_logs
    if not isinstance(logs, list):
        return {}, ["trace-missing-structLogs"]
    mapping: dict[int, str] = {}
    problems: list[str] = []
    for index, log in enumerate(logs):
        if not isinstance(log, dict) or log.get("op") not in STORAGE_OPCODES:
            continue
        frame_id = log.get("frameId")
        if not isinstance(frame_id, str) or frame_id not in known:
            problems.append(f"log-{index}:missing-or-unknown-frame-id")
        else:
            mapping[index] = frame_id
    return mapping, problems


def normalize_struct_logs(payload: Any, *, tx_index: int,
                          call_trace: Any = None) -> tuple[list[dict[str, Any]], list[str]]:
    """Return normalized storage accesses and capability problems.

    A context address is mandatory for storage accesses.  It may be supplied
    by an explicit ``storageContextAddress`` field in a custom trace.  It is
    never guessed from ``to``/``address`` because that is wrong under
    DELEGATECALL.
    """
    logs = payload.get("structLogs") if isinstance(payload, dict) else payload
    if not isinstance(logs, list):
        return [], ["trace-missing-structLogs"]
    accesses: list[dict[str, Any]] = []
    problems: list[str] = []
    frame_ids, frame_problems = reconstruct_frame_ids(payload, call_trace) if call_trace is not None else ({}, [])
    if call_trace is not None:
        problems.extend(frame_problems)
    for index, raw in enumerate(logs):
        if not isinstance(raw, dict):
            problems.append(f"log-{index}:not-object")
            continue
        op = raw.get("op")
        if op not in STORAGE_OPCODES:
            continue
        pc, depth = raw.get("pc"), raw.get("depth")
        stack = raw.get("stack")
        context = raw.get("storageContextAddress")
        if not isinstance(pc, int) or not isinstance(depth, int):
            problems.append(f"log-{index}:missing-pc-or-depth")
            continue
        if not isinstance(stack, list) or not stack:
            problems.append(f"log-{index}:missing-stack")
            continue
        if not isinstance(context, str) or not context.startswith("0x"):
            problems.append(f"log-{index}:missing-storage-context-address")
            continue
        if call_trace is not None and index not in frame_ids:
            continue
        slot = _hex(stack[-1] if op == "SLOAD" else (stack[-1] if len(stack) >= 2 else None))
        if slot is None:
            problems.append(f"log-{index}:missing-slot")
            continue
        accesses.append(asdict(Access(tx_index, pc, depth, op, context.lower(), slot,
                                       raw.get("codeAddress"), frame_ids.get(index))))
    return accesses, problems


def classify_failures(failures: list[dict[str, Any]], canonical: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Classify local failures without treating absence as proof of emergence."""
    keys = {(int(a["tx_index"]), int(a["pc"]), int(a["depth"]), a["opcode"],
             a["storage_context_address"].lower(), a["storage_slot"].lower())
            for a in canonical}
    result = []
    for failure in failures:
        required = ("tx_index", "pc", "depth", "opcode", "storage_context_address", "slot")
        if not all(k in failure and failure[k] is not None for k in required):
            category = "UNRESOLVED_PROVENANCE"
        else:
            key = (int(failure["tx_index"]), int(failure["pc"]), int(failure["depth"]),
                   failure["opcode"], failure["storage_context_address"].lower(), failure["slot"].lower())
            if key in keys:
                category = "DETERMINISTIC_ACQUISITION_GAP"
            elif failure.get("path_diverged") is True:
                category = "SEQUENTIAL_OR_PATH_DEPENDENT_CANDIDATE"
            else:
                category = "UNRESOLVED_PROVENANCE"
        result.append({**failure, "classification": category})
    return result
