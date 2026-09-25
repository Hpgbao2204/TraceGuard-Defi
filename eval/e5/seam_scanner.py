"""Phase-1 seam-group scanner over canonical frozen B2 traces.

This is an evidence enumerator only. It never mutates state or infers that a
detected seam is the root cause. Occurrences are grouped by semantic read
family and callee, not by individual call site.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from eval.b2_run_select import select_canonical_run

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "docs/m4_frozen_case_manifest.json"
PRE = ROOT / "eval/results/m6_b2_preflight.json"
OUT = ROOT / "eval/results/e5_rcfh/seam_groups"
SELECTORS = {
    "0xfeaf968c": ("oracle_read", "Chainlink.latestRoundData"),
    "0x0902f1ac": ("amm_reserve_read", "UniswapV2Pair.getReserves"),
    "0xab9c4b5d": ("flashloan_capital", "AaveV2.flashLoan"),
    "0xe0232b42": ("flashloan_capital", "MorphoBlue.flashLoan"),
    "0x5cffe9de": ("flashloan_capital", "ERC3156.flashLoan"),
    "0x5c38449e": ("flashloan_capital", "BalancerVault.flashLoan"),
    "0x1626ba7e": ("auth_check", "ERC1271.isValidSignature"),
}


def _selector(inp: Any) -> str | None:
    if not isinstance(inp, str) or not inp.startswith("0x") or len(inp) < 10:
        return None
    return inp[:10].lower()


def _exit_for(trace: list[dict[str, Any]], index: int, frame: dict[str, Any]) -> dict[str, Any]:
    for item in trace[index + 1 :]:
        if item.get("event") == "exit" and item.get("depth") == frame.get("depth"):
            return item
    return {}


def scan_row(row: dict[str, Any]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], dict[str, Any]] = {}
    trace = row.get("call_trace") or []
    for index, frame in enumerate(trace):
        if frame.get("event") != "enter":
            continue
        selector = _selector(frame.get("input"))
        if selector not in SELECTORS:
            continue
        operator, semantic = SELECTORS[selector]
        callee = str(frame.get("to") or "").lower()
        key = (operator, callee, selector)
        group = groups.setdefault(key, {
            "group_id": f"g{len(groups)}",
            "type": operator,
            "semantic": semantic,
            "callee": callee,
            "selector": selector,
            "operator": {"oracle_read": "OraclePin", "amm_reserve_read": "AmmReservePin", "flashloan_capital": "FlashLoanCapitalSubstitution", "auth_check": "AuthCheckReviewRequired"}[operator],
            "occurrences": [],
        })
        exit_row = _exit_for(trace, index, frame)
        group["occurrences"].append({
            "trace_index": index,
            "depth": frame.get("depth"),
            "caller": frame.get("from"),
            "callee": frame.get("to"),
            "selector": selector,
            "input": frame.get("input"),
            "returndata": exit_row.get("output"),
            "status": exit_row.get("status"),
        })
    return list(groups.values())


def main() -> None:
    manifest = json.loads(MANIFEST.read_text())["cases"]
    preflight = {x["case_id"]: x for x in json.loads(PRE.read_text())["cases"]}
    OUT.mkdir(parents=True, exist_ok=True)
    summary = []
    for case in manifest:
        context = preflight[case["case_id"]]["context"]
        row = select_canonical_run(context, case["tx_hash"])
        groups = scan_row(row)
        payload = {
            "schema_version": 1,
            "artifact": "e5-seam-groups",
            "corpus_id": "m4-frozen-20",
            "case_id": case["case_id"],
            "tx_hash": case["tx_hash"],
            "canonical_run": row["_run_name"],
            "canonical_content_sha256": row["_content_sha256"],
            "resolver_versions": {"run_select": "v1", "seam_scanner": "e5-seam-groups-v1"},
            "seam_groups": groups,
        }
        (OUT / f"{case['case_id']}.json").write_text(json.dumps(payload, indent=2) + "\n")
        summary.append({"case_id": case["case_id"], "group_count": len(groups), "occurrence_count": sum(len(g["occurrences"]) for g in groups)})
    report = {"schema_version": 1, "scope": "m4-frozen-20", "resolver_version": "e5-seam-groups-v1", "case_count": len(summary), "cases": summary, "total_groups": sum(x["group_count"] for x in summary), "total_occurrences": sum(x["occurrence_count"] for x in summary)}
    (OUT.parent / "seam_scan_summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
