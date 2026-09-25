"""Fail-closed manifest and comparison helpers for M4 differential validation.

This module does not acquire RPC evidence or select cases.  It validates a
predeclared case manifest and compares already-materialized B2 and independent
execution evidence.  Missing evidence is an inconclusive result, never a
pass-by-default.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import argparse
import re
from typing import Any, Mapping


SCHEMA_VERSION = 1
REQUIRED_CASE_FIELDS = frozenset({
    "case_id", "tx_hash", "block", "tx_index", "context_manifest_hash",
    "b2_source", "independent_source", "independent_engine",
    "independent_version",
})
COMPARISON_FIELDS = ("status", "gas_used", "logs_hash", "relevant_state_hash")
SHA256_HEX = re.compile(r"^[0-9a-fA-F]{64}$")
CANONICAL_FROZEN_SET_SHA256 = "5db36702f741e874c208874b841cc6acb7bcb863b7a2a257926aee2f5002bd90"


def frozen_case_set_hash(cases: list[Mapping[str, Any]]) -> str:
    """Hash the canonical case identities, independent of JSON formatting."""
    identities = sorted(({
        "case_id": str(case["case_id"]), "tx_hash": str(case["tx_hash"]).lower(),
        "block": int(case["block"]), "tx_index": int(case["tx_index"])
    } for case in cases), key=lambda item: (
        item["case_id"], item["tx_hash"], item["block"], item["tx_index"]))
    return evidence_hash(identities)


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_digest(value: Any) -> bool:
    return isinstance(value, str) and bool(SHA256_HEX.fullmatch(value))


def validate_manifest(manifest: Mapping[str, Any]) -> None:
    """Validate the frozen M4 manifest contract without reading the network."""
    if not isinstance(manifest, Mapping):
        raise ValueError("M4 manifest must be an object")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported M4 manifest schema version")
    if not _nonempty_string(manifest.get("source_commit")):
        raise ValueError("M4 source_commit is required")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or len(cases) != 20:
        raise ValueError("M4 frozen manifest must contain exactly 20 cases")
    if not _is_digest(manifest.get("frozen_set_sha256")):
        raise ValueError("M4 frozen_set_sha256 is required")
    if manifest["frozen_set_sha256"].lower() != frozen_case_set_hash(cases):
        raise ValueError("M4 frozen_set_sha256 does not match canonical case set")
    if manifest["frozen_set_sha256"].lower() != CANONICAL_FROZEN_SET_SHA256:
        raise ValueError("M4 manifest is not the repository's frozen case set")
    seen: set[str] = set()
    for index, case in enumerate(cases):
        if not isinstance(case, Mapping):
            raise ValueError(f"M4 case {index} must be an object")
        missing = sorted(REQUIRED_CASE_FIELDS - set(case))
        if missing:
            raise ValueError(f"M4 case {index} missing fields: {missing}")
        case_id = case["case_id"]
        if not _nonempty_string(case_id) or case_id in seen:
            raise ValueError(f"M4 case {index} has duplicate/invalid case_id")
        seen.add(case_id)
        if not _nonempty_string(case["tx_hash"]):
            raise ValueError(f"M4 case {index} tx_hash is required")
        if not isinstance(case["block"], int) or case["block"] < 0:
            raise ValueError(f"M4 case {index} block is invalid")
        if not isinstance(case["tx_index"], int) or case["tx_index"] < 0:
            raise ValueError(f"M4 case {index} tx_index is invalid")
        for field in ("context_manifest_hash", "b2_source", "independent_source",
                      "independent_engine", "independent_version"):
            if not _nonempty_string(case[field]):
                raise ValueError(f"M4 case {index} {field} is required")
        if not _is_digest(case["context_manifest_hash"]):
            raise ValueError(f"M4 case {index} context_manifest_hash is invalid")
        if case["b2_source"] == case["independent_source"]:
            raise ValueError(f"M4 case {index} sources must be independent")


def compare_execution_evidence(
    b2: Mapping[str, Any] | None,
    independent: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Compare the declared execution evidence fields fail-closed."""
    if not isinstance(b2, Mapping) or not isinstance(independent, Mapping):
        return {"outcome": "INCONCLUSIVE", "reason": "execution evidence missing"}
    missing = [
        field for field in COMPARISON_FIELDS
        if field not in b2 or field not in independent
        or b2[field] is None or independent[field] is None
    ]
    if missing:
        return {
            "outcome": "INCONCLUSIVE",
            "reason": f"required comparison evidence missing: {missing}",
            "missing_fields": missing,
        }
    if (not isinstance(b2["status"], bool) or
            not isinstance(independent["status"], bool) or
            not isinstance(b2["gas_used"], int) or b2["gas_used"] < 0 or
            not isinstance(independent["gas_used"], int) or independent["gas_used"] < 0 or
            any(not _is_digest(item)
                for item in (b2["logs_hash"], independent["logs_hash"],
                             b2["relevant_state_hash"],
                             independent["relevant_state_hash"]))):
        return {"outcome": "INCONCLUSIVE", "reason": "invalid execution evidence types"}
    comparisons = {field: b2[field] == independent[field]
                   for field in COMPARISON_FIELDS}
    mismatches = [field for field, matched in comparisons.items() if not matched]
    return {
        "outcome": "PASS" if not mismatches else "INCONCLUSIVE",
        "comparisons": comparisons,
        "mismatches": mismatches,
        "reason": "all required fields match" if not mismatches
                  else f"evidence mismatch: {mismatches}",
    }


def evidence_hash(value: Any) -> str:
    """Hash JSON evidence deterministically for cross-run comparison."""
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def canonical_logs(logs: Any) -> list[dict[str, Any]]:
    """Project client-specific receipt logs onto the EVM-observable fields."""
    if not isinstance(logs, list):
        raise ValueError("logs must be a list")
    result = []
    for log in logs:
        if not isinstance(log, Mapping):
            raise ValueError("log must be an object")
        address = log.get("address")
        data = log.get("data", "0x")
        topics = log.get("topics", [])
        if not isinstance(address, str) or not isinstance(data, str) or not isinstance(topics, list):
            raise ValueError("invalid log fields")
        result.append({"address": address.lower(),
                       "topics": [str(topic).lower() for topic in topics],
                       "data": data.lower()})
    return result


def execution_evidence(
    *, status: bool | None, gas_used: int | None,
    logs: Any = None, relevant_post_state: Any = None,
) -> dict[str, Any]:
    """Normalize one execution result into the M4 comparison schema.

    Raw logs and relevant post-state must be supplied explicitly.  ``None``
    remains missing so the comparator cannot mistake unavailable evidence for
    an empty list/object.
    """
    return {
        "status": status,
        "gas_used": gas_used,
        "logs_hash": evidence_hash(logs) if logs is not None else None,
        "relevant_state_hash": (
            evidence_hash(relevant_post_state)
            if relevant_post_state is not None else None
        ),
    }


def compare_manifest_evidence(
    manifest: Mapping[str, Any],
    evidence: Mapping[str, Mapping[str, Mapping[str, Any]]],
) -> dict[str, Any]:
    """Compare every manifest case with independently supplied evidence.

    ``evidence`` is keyed by case ID and contains ``b2`` and ``independent``
    records.  Provenance metadata is mandatory at this boundary so an
    otherwise matching execution cannot be attached to the wrong case or
    source commit.  This function only reports differential validation; it
    never creates a causal verdict.
    """
    validate_manifest(manifest)
    cases = {str(case["case_id"]): case for case in manifest["cases"]}
    if set(evidence) != set(cases):
        missing = sorted(set(cases) - set(evidence))
        extra = sorted(set(evidence) - set(cases))
        return {
            "outcome": "INCONCLUSIVE",
            "reason": "manifest/evidence case set mismatch",
            "missing_cases": missing,
            "extra_cases": extra,
            "cases": [],
        }

    results: list[dict[str, Any]] = []
    for case_id, case in cases.items():
        pair = evidence.get(case_id)
        if not isinstance(pair, Mapping):
            results.append({"case_id": case_id, "outcome": "INCONCLUSIVE",
                            "reason": "case evidence missing"})
            continue
        case_result = {"case_id": case_id}
        provenance_errors: list[str] = []
        for side in ("b2", "independent"):
            record = pair.get(side)
            if not isinstance(record, Mapping):
                provenance_errors.append(f"{side} evidence missing")
                continue
            if side == "b2":
                if record.get("source_commit") != manifest["source_commit"]:
                    provenance_errors.append("b2 source_commit mismatch")
                if record.get("source") != case["b2_source"]:
                    provenance_errors.append("b2 source mismatch")
            else:
                if record.get("source") != case["independent_source"]:
                    provenance_errors.append("independent source mismatch")
                if record.get("engine") != case["independent_engine"]:
                    provenance_errors.append("independent engine mismatch")
                if record.get("version") != case["independent_version"]:
                    provenance_errors.append("independent version mismatch")
            for field in ("case_id", "tx_hash", "block", "tx_index"):
                if record.get(field) != case[field]:
                    provenance_errors.append(f"{side} {field} mismatch")
            if side == "b2" and record.get("context_manifest_hash") != case["context_manifest_hash"]:
                provenance_errors.append("b2 context_manifest_hash mismatch")
        if provenance_errors:
            case_result.update(outcome="INCONCLUSIVE",
                               reason="provenance mismatch",
                               provenance_errors=provenance_errors)
        elif pair["b2"].get("acceptance_gate") is not True:
            case_result.update(outcome="INCONCLUSIVE",
                               reason="B2 acceptance gate failed",
                               b2_acceptance_gate=pair["b2"].get("acceptance_gate"))
        else:
            comparison = compare_execution_evidence(pair["b2"], pair["independent"])
            case_result.update(comparison)
        results.append(case_result)
    passed = sum(item.get("outcome") == "PASS" for item in results)
    return {
        "outcome": "PASS" if passed == len(results) else "INCONCLUSIVE",
        "cases": results,
        "case_count": len(results),
        "passed_cases": passed,
        "inconclusive_cases": len(results) - passed,
    }


def load_and_compare(manifest_path: Path, evidence_path: Path) -> dict[str, Any]:
    """Load two explicit JSON artifacts and return the deterministic summary."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    if not isinstance(evidence, Mapping):
        raise ValueError("M4 evidence bundle must be an object keyed by case_id")
    return compare_manifest_evidence(manifest, evidence)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    result = load_and_compare(args.manifest, args.evidence)
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(encoded, encoding="utf-8", newline="\n")
    else:
        print(encoded, end="")
    return 0 if result.get("outcome") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
