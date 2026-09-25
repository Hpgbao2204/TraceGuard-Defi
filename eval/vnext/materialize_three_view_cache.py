"""Materialize vNext three-view cache with explicit missingness."""
from __future__ import annotations
import hashlib, json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.vnext.vnext_contract import VNEXT_B0_VIEWS, VNEXT_B0_FEATURE_CONTRACT_VERSION
from eval.e1_common import load_cache_rows, trace_from_cache
from core.views import evaluate_all

POS = ROOT / "corpus/vnext/positive_transactions.jsonl"
LEGACY = ROOT / "eval/results/e1_trace_cache.jsonl"
RECOVERED_BSC = ROOT / "eval/vnext/acquisition/bsc_positive_trace_cache.jsonl"
RECOVERED_OTHER = [ROOT / f"eval/vnext/acquisition/{c}_positive_trace_cache.jsonl" for c in ("ethereum", "arbitrum", "optimism")]
OUT = ROOT / "eval/vnext/features/three_view_feature_cache.jsonl"
MANIFEST = ROOT / "eval/vnext/features/three_view_feature_manifest.json"

def main() -> None:
    positives = [json.loads(x) for x in POS.read_text().splitlines() if x.strip()]
    wanted = {x["tx_hash"]: x for x in positives}
    legacy = load_cache_rows(LEGACY)
    if RECOVERED_BSC.exists():
        legacy.update(load_cache_rows(RECOVERED_BSC))
    for recovered in RECOVERED_OTHER:
        if recovered.exists():
            legacy.update(load_cache_rows(recovered))
    rows = []
    missing_cache = []
    for tx_hash, meta in sorted(wanted.items()):
        source = legacy.get(tx_hash)
        if not source or source.get("error") or source.get("status") is False:
            missing_cache.append(tx_hash)
            continue
        result = evaluate_all(trace_from_cache(source.get("trace") or {}), {})
        scores = {view: (result.get(view, {}).get("score") if result.get(view, {}).get("coverage") else None) for view in VNEXT_B0_VIEWS}
        # Frozen vNext policy: successful receipt + complete logs + no ERC-20
        # Transfer means observed zero token flow, not missing evidence.
        token = result.get("token_flow", {})
        logs = (source.get("trace") or {}).get("logs") or []
        has_transfer = any(str((log.get("topics") or [""])[0]).lower().startswith("0xddf252ad") for log in logs)
        if not token.get("coverage") and source.get("status") is True and logs and not has_transfer:
            scores["token_flow"] = 0.0
        missing = sorted(view for view, score in scores.items() if score is None)
        rows.append({
            **meta,
            "feature_schema_version": VNEXT_B0_FEATURE_CONTRACT_VERSION,
            "scores": scores,
            "missing_views": missing,
            "coverage_complete": not missing,
            "source_cache": "eval/results/e1_trace_cache.jsonl",
        })
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("".join(json.dumps(x, sort_keys=True) + "\n" for x in rows))
    manifest = {
        "schema_version": 1,
        "status": "MATERIALIZED_WITH_EXPLICIT_MISSINGNESS" if rows else "NOT_MATERIALIZED",
        "rows": len(rows), "requested_rows": len(positives),
        "missing_cache_rows": len(missing_cache),
        "rows_with_missing_views": sum(bool(x["missing_views"]) for x in rows),
        "views": list(VNEXT_B0_VIEWS),
        "missing_policy": "explicit_missing; never substitute 0.0",
        "source_cache_sha256": hashlib.sha256(LEGACY.read_bytes()).hexdigest(),
        "recovered_bsc_cache_sha256": hashlib.sha256(RECOVERED_BSC.read_bytes()).hexdigest() if RECOVERED_BSC.exists() else None,
        "cache_sha256": hashlib.sha256(OUT.read_bytes()).hexdigest(),
        "missing_cache_tx_hashes": missing_cache,
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps(manifest, indent=2, sort_keys=True))

if __name__ == "__main__":
    main()
