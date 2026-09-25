"""Full frozen-20 M6 orchestration over already-frozen B2 contexts.

This deliberately starts with a preflight-only mode.  It never reacquires
historical state and never substitutes Anvil for a missing B2 context.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from eval.b2_adapter import run as run_b2
from core.env import load_dotenv, resolve_rpc_candidates, resolve_trace_rpc_candidates
from core.rpc import RpcClient
from eval.e4.execution import run_necessity
from eval.e4.models import Case
from eval.e4.planner import build_mutation_plan
from eval.e4_necessity import load_trace_cache
from eval.necessity import mutation_factor

ROOT = Path(__file__).resolve().parent.parent
FIXED = ROOT / "docs" / "m4_frozen_case_manifest.json"
QUEUE = ROOT / "eval" / "e4_fixed_set_v2.json"
CONTEXTS = ROOT / "eval" / "results" / "m4" / "b2-contexts-fresh"
M4_BUNDLE = ROOT / "eval" / "results" / "m4" / "m4_b2_vs_liquify_20.json"


def materialize_harm_spec(raw: dict | None, *, target_block: int) -> dict | None:
    """Convert Reviewer-C worksheet values to the executable harm schema."""
    if not isinstance(raw, dict):
        return None
    victims = raw.get("victims") or []
    addresses = [str(v.get("address", "")).lower() if isinstance(v, dict)
                 else str(v).lower() for v in victims]
    addresses = [v for v in addresses if v.startswith("0x") and len(v) == 42]
    if not addresses:
        return None
    prices = raw.get("token_prices") or {}
    assets = {}
    for token, metadata in prices.items():
        if not isinstance(metadata, dict):
            continue
        address = str(metadata.get("asset_address") or "").lower()
        symbol = str(metadata.get("symbol") or token)
        kind = metadata.get("asset_kind")
        if symbol.upper() in {"ETH", "NATIVE ETH", "NATIVE"}:
            kind, address = "native", None
        elif kind == "erc20" and len(address) == 42 and address.startswith("0x"):
            kind = "erc20"
        else:
            kind, address = "unknown", None
        assets[str(token).lower()] = {**metadata, "symbol": symbol,
                                      "asset_kind": kind, "asset_address": address}
    provenance = {
        str(token).lower(): {
            "reference_block": target_block - 1,
            "source": raw.get("valuation_source") or "Reviewer C adjudicated valuation",
        }
        for token in prices
    }
    return {**raw, "victims": addresses, "token_prices": assets,
            "target_block": target_block,
            "price_reference_block": target_block - 1,
            "price_provenance": provenance}


def materialize_harm_manifest(sidecar_path: Path, fixed_path: Path, out: Path) -> dict:
    sidecar = {json.loads(line)["case_id"]: json.loads(line)
               for line in sidecar_path.read_text(encoding="utf-8").splitlines() if line.strip()}
    result = {"schema_version": 2, "source_sidecar_sha256": sha256(sidecar_path),
              "fixed_set_sha256": sha256(fixed_path), "cases": {}}
    for case in load_cases(fixed_path):
        spec = materialize_harm_spec(sidecar.get(case["case_id"], {}).get("harm_spec"),
                                     target_block=int(case["block"]))
        if not spec:
            status, reason = "UNMEASURABLE_MISSING_PROTECTED_ENTITY", "no valid 20-byte victim address"
        elif any(v.get("asset_kind") == "unknown" for v in spec.get("token_prices", {}).values()):
            status, reason = "UNMEASURABLE_MISSING_ASSET_MAPPING", "token price lacks explicit native/ERC20 asset mapping"
        else:
            status, reason = "MEASURABLE", None
        result["cases"][case["case_id"]] = {
            "status": status,
            "harm_spec": spec,
            "reason": reason,
        }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def build_scope_matrix(sidecar_path: Path, fixed_path: Path, out: Path) -> dict:
    sidecar = {json.loads(line)["case_id"]: json.loads(line)
               for line in sidecar_path.read_text(encoding="utf-8").splitlines() if line.strip()}
    rows = []
    for case in load_cases(fixed_path):
        factors = (sidecar.get(case["case_id"], {}).get("root_cause_gt") or [])
        factors = [str(x).rstrip("?") for x in factors]
        supported = sorted(set(factors) & {"f_fl", "f_orc"})
        adjudication = sidecar.get(case["case_id"], {}).get("adjudication") or {}
        evidence_text = " ".join(str(value) for value in (
            sidecar.get(case["case_id"], {}).get("enabling_primitives") or [],
            sidecar.get(case["case_id"], {}).get("causal_calls") or [],
            [adjudication.get("note", "")],
            [sidecar.get(case["case_id"], {}).get("security_objective") or ""],
        )).lower()
        amm_terms = ("amm_reserve", "getreserves", "reserve manipulation",
                     "pool reserve", "uniswap v2 reserve")
        subtype = ("f_orc_amm" if "f_orc" in supported and
                   any(term in evidence_text for term in amm_terms)
                   else ("f_orc_external" if "f_orc" in supported else None))
        if subtype == "f_orc_amm":
            supported = []
        rows.append({"case_id": case["case_id"], "ground_truth_factors": factors,
                     "mechanism_subtype": subtype,
                     "release_operators": supported,
                     "status": "SUPPORTED" if supported else "OUT_OF_SCOPE_OR_UNSUPPORTED",
                     "reason": "AMM reserve oracle is outside external-feed scope" if subtype == "f_orc_amm" else None})
    result = {"schema_version": 2, "release_scope": ["f_fl", "f_orc_external"],
              "fixed_set_sha256": sha256(fixed_path), "cases": rows}
    result["summary"] = {
        "fixed_cases": len(rows),
        "release_operator_supported_cases": sum(1 for c in rows if c["release_operators"]),
        "amm_out_of_scope_cases": sum(1 for c in rows if c["mechanism_subtype"] == "f_orc_amm"),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_cases(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    cases = data.get("cases") or []
    if len(cases) != 20:
        raise ValueError(f"frozen M6 set must contain exactly 20 cases, got {len(cases)}")
    return cases


def context_for(case: dict) -> Path:
    return CONTEXTS / case["case_id"]


def preflight(fixed_path: Path = FIXED, contexts: Path = CONTEXTS,
              m4_bundle: Path = M4_BUNDLE) -> dict:
    cases = load_cases(fixed_path)
    m4 = json.loads(m4_bundle.read_text(encoding="utf-8"))
    rows = []
    for case in cases:
        root = contexts / case["case_id"]
        item = {"case_id": case["case_id"], "context": str(root), "ok": False}
        try:
            actual = json.loads((root / "case.json").read_text(encoding="utf-8"))
            m4_case = m4.get(case["case_id"], {}).get("b2", {})
            checks = {
                "tx_hash": str(actual.get("tx_hash", "")).lower() == str(case["tx_hash"]).lower(),
                "block": int(actual["block"]) == int(case["block"]),
                "tx_index": int(actual["tx_index"]) == int(case["tx_index"]),
                "required_files": all((root / name).is_file() for name in (
                    "block.json", "ancestors.json", "transactions.json", "receipts.json",
                    "prestates.json", "poststates.json", "prestate_proofs.json")),
                "m4_context_hash": sha256(root / "manifest.json") == m4_case.get("context_manifest_hash"),
            }
            if not all(checks.values()):
                item["checks"] = checks
            else:
                result = run_b2(root, timeout=300, target_index=int(case["tx_index"]))
                item.update({"checks": checks, "acceptance_gate": bool(result.payload.get("acceptance_gate")),
                             "proof_verified": result.proof_verified, "error": result.error})
                item["ok"] = all(checks.values()) and bool(result.payload.get("acceptance_gate"))
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            item["error"] = f"{type(exc).__name__}: {exc}"
        rows.append(item)
    return {"schema_version": 1, "fixed_set_sha256": sha256(fixed_path),
            "case_count": len(cases), "ready": all(x["ok"] for x in rows),
            "cases": rows}


def execute(fixed_path: Path, contexts: Path, preflight_path: Path,
            out: Path, timeout: int) -> dict:
    check = json.loads(preflight_path.read_text(encoding="utf-8"))
    if not check.get("ready"):
        raise RuntimeError("B2 preflight is not ready; refusing mutation execution")
    queue = json.loads(QUEUE.read_text(encoding="utf-8"))
    trace_cache = load_trace_cache(ROOT / "eval/results/e1_trace_cache.jsonl")
    sidecar_path = ROOT / "corpus/annotations/adjudication/e4_adjudication_completed_reviewer_c.jsonl"
    harm_path = ROOT / "eval/results/m6_harm_spec_v2.json"
    if not harm_path.is_file():
        raise RuntimeError("harm_spec_v2 manifest missing; run --materialize-harm first")
    harm_manifest = json.loads(harm_path.read_text(encoding="utf-8"))
    load_dotenv()
    archives = resolve_rpc_candidates("mainnet")
    traces = resolve_trace_rpc_candidates("mainnet")
    if not archives:
        raise RuntimeError("no archive RPC configured")
    archive = RpcClient(archives[0], timeout=min(timeout, 30), attempts=1,
                        fallback_urls=archives[1:])
    trace = RpcClient(traces[0], timeout=min(timeout, 30), attempts=1,
                      fallback_urls=traces[1:]) if traces else None
    out.parent.mkdir(parents=True, exist_ok=True)
    done = {}
    if out.exists():
        for line in out.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line); done[row["case_id"]] = row
    with out.open("a", encoding="utf-8") as fp:
        for case in load_cases(fixed_path):
            cid = case["case_id"]
            if cid in done:
                continue
            root = contexts / cid
            source = next(x for x in queue["cases"] if x["case_id"] == cid)
            try:
                context_case = json.loads((root / "case.json").read_text(encoding="utf-8"))
                txs = json.loads((root / "transactions.json").read_text(encoding="utf-8"))
                receipts = json.loads((root / "receipts.json").read_text(encoding="utf-8"))
                receipt = receipts[-1]
                frozen_case = {"tx_hash": case["tx_hash"], "block": case["block"],
                               "tx_index": case["tx_index"]}
                adjudicated = (harm_manifest.get("cases", {}).get(cid) or {})
                case = Case(cid, cid, source.get("selection_stratum", "unknown"),
                            frozen_case["tx_hash"], block=int(frozen_case["block"]),
                            tx_index=int(frozen_case["tx_index"]),
                            prior_hashes=[x["hash"] for x in txs[:-1]],
                            mainnet_gas=int(receipt.get("gasUsed", "0x0"), 16),
                            extra={"paper_eligible": True,
                                   "harm_spec": adjudicated.get("harm_spec")},
                            trace=trace_cache.get(cid) or trace_cache.get(frozen_case["tx_hash"].lower()))
                if case.trace is None and trace is not None:
                    case.trace = trace.call_tracer(frozen_case["tx_hash"])
                plan = build_mutation_plan(case, archive, trace_rpc=trace)
                mutations = [m for m in plan.mutations if mutation_factor(str(m)) in {"f_fl", "f_orc"}]
                if not mutations:
                    rows = [{"case_id": cid, "status": "INCONCLUSIVE",
                             "reason": "unsupported_mutation", "planner_notes": plan.notes}]
                else:
                    rows = run_necessity(case, mutations, archive=archive,
                                         b2_context=root, run_id=f"m6-b2-{cid}",
                                         timeout=timeout)
                result = {"case_id": cid, "status": "terminal", "rows": rows}
            except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                result = {"case_id": cid, "status": "ORCHESTRATOR_ERROR",
                          "reason": f"{type(exc).__name__}: {exc}"}
            except Exception as exc:
                result = {"case_id": cid, "status": "INCONCLUSIVE",
                          "reason": f"execution_failure:{type(exc).__name__}: {exc}"}
            fp.write(json.dumps(result, ensure_ascii=False) + "\n"); fp.flush()
            done[cid] = result
    scientific_inconclusive = sum(
        any(str(row.get("verdict", "")).startswith("INCONCLUSIVE") or
            row.get("reason") == "unsupported_mutation"
            for row in (item.get("rows") or []))
        for item in done.values()
    )
    summary = {"schema_version": 1, "fixed_case_count": 20,
               "completed_cases": len(done),
               "terminal_cases": len(done) == 20,
               "scientific_inconclusive_cases": scientific_inconclusive,
               "output": str(out)}
    out.with_name("summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixed", type=Path, default=FIXED)
    parser.add_argument("--contexts", type=Path, default=CONTEXTS)
    parser.add_argument("--m4-bundle", type=Path, default=M4_BUNDLE)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--results-out", type=Path,
                        default=ROOT / "eval/results/m6_b2_results.json")
    parser.add_argument("--materialize-harm", action="store_true")
    parser.add_argument("--harm-out", type=Path,
                        default=ROOT / "eval/results/m6_harm_spec_v2.json")
    parser.add_argument("--scope-audit", action="store_true")
    parser.add_argument("--scope-out", type=Path,
                        default=ROOT / "eval/results/m6_operator_scope_matrix.json")
    parser.add_argument("--out", type=Path, default=ROOT / "eval/results/m6_b2_preflight.json")
    args = parser.parse_args()
    if args.materialize_harm:
        result = materialize_harm_manifest(
            ROOT / "corpus/annotations/adjudication/e4_adjudication_completed_reviewer_c.jsonl",
            args.fixed, args.harm_out)
        print(json.dumps({"schema_version": result["schema_version"],
                          "case_count": len(result["cases"]), "output": str(args.harm_out),
                          "measurable": sum(x["status"] == "MEASURABLE" for x in result["cases"].values()),
                          "unmeasurable": sum(x["status"] != "MEASURABLE" for x in result["cases"].values())}, indent=2))
        return 0
    if args.scope_audit:
        result = build_scope_matrix(
            ROOT / "corpus/annotations/adjudication/e4_adjudication_completed_reviewer_c.jsonl",
            args.fixed, args.scope_out)
        print(json.dumps({"case_count": len(result["cases"]), "output": str(args.scope_out)}, indent=2))
        return 0
    if args.execute:
        result = execute(args.fixed, args.contexts, args.out,
                         args.results_out, args.timeout)
        print(json.dumps(result, indent=2)); return 0 if result["terminal_cases"] else 2
    result = preflight(args.fixed, args.contexts, args.m4_bundle)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ready": result["ready"], "case_count": result["case_count"],
                      "output": str(args.out)}, indent=2))
    return 0 if result["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
