"""Diagnostic dose-response probe over one frozen AMM seam.

This is deliberately not a causal E5 verdict: VETH's reviewed claim is
flash-loan related, while this probe exercises the observed AMM seam only.
It records raw E4 replay rows for each reserve dose.
"""
from __future__ import annotations

import json
from pathlib import Path

from core.env import load_dotenv, resolve_rpc_candidates
from core.mutate import AmmReservePin
from core.rpc import RpcClient
from eval.e4.execution import run_necessity
from eval.e4.models import Case
from eval.e4.pricing import harm_spec_from_manifest, load_price_manifest
from eval.e4.reporting import write_csv
from eval.b2_adapter import run as run_b2

ROOT = Path(__file__).resolve().parents[2]
CASE_ID = "defihacklabs-veth-2024-11-14"
POOL = "0x582d17d24127cfdcbc8c4e0a40c12d77b2e7a48d"
SLOT = "0x" + "00" * 31 + "08"
POINTS = 5
MASK112 = (1 << 112) - 1


def _row_accounts(context: Path, filename: str, key: str, index: int) -> dict:
    row = json.loads((context / filename).read_text())[index]
    value = row.get(key, {})
    return json.loads(value) if isinstance(value, str) else value


def _decode_pair(word: int) -> tuple[int, int, int]:
    return word & MASK112, (word >> 112) & MASK112, word >> 224


def _encode_pair(reserve0: int, reserve1: int, timestamp: int) -> int:
    if not (0 <= reserve0 <= MASK112 and 0 <= reserve1 <= MASK112):
        raise ValueError("reserve does not fit uint112")
    if not (0 <= timestamp <= 0xFFFFFFFF):
        raise ValueError("timestamp does not fit uint32")
    return reserve0 | (reserve1 << 112) | (timestamp << 224)


def main() -> int:
    load_dotenv()
    context = ROOT / "eval/results/m4/b2-contexts-fresh" / CASE_ID
    fixed = {x["case_id"]: x for x in json.loads((ROOT / "eval/e4_fixed_set_v2.json").read_text())["cases"]}
    item = fixed[CASE_ID]
    cache = {}
    for line in (ROOT / "eval/results/e1_trace_cache.jsonl").read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            cache[row["tx_hash"].lower()] = row

    urls = resolve_rpc_candidates("mainnet")
    archive = RpcClient(urls[0], timeout=60, attempts=2, fallback_urls=urls[1:])
    tx = archive.eth_get_transaction(item["tx_hash"])
    receipt = archive.eth_get_receipt(item["tx_hash"])
    gate = run_b2(context, timeout=900)
    if not gate.payload.get("acceptance_gate", False):
        raise RuntimeError(f"canonical B2 gate failed: {gate.payload}")

    # The canonical pool state is attached to the trace index that contains
    # the observed getReserves call; do not merge unrelated per-frame states.
    pre_rows = json.loads((context / "prestates.json").read_text())
    state_index = next(i for i, row in enumerate(pre_rows)
                       if POOL in {str(a).lower() for a in row.get("trace", {})})
    accounts = _row_accounts(context, "prestates.json", "trace", state_index)
    pre = int(accounts[POOL]["storage"][SLOT], 16)
    post_accounts = _row_accounts(context, "poststates.json", "poststate", state_index)
    post = int(post_accounts[POOL]["storage"][SLOT], 16)
    pre0, pre1, pre_timestamp = _decode_pair(pre)
    post0, post1, post_timestamp = _decode_pair(post)
    doses = [
        _encode_pair(
            int(pre0 + (post0 - pre0) * i / (POINTS - 1)),
            int(pre1 + (post1 - pre1) * i / (POINTS - 1)),
            pre_timestamp,
        )
        for i in range(POINTS)
    ]

    manifest = load_price_manifest(ROOT / "eval/e4_price_manifest.json")
    harm_spec = harm_spec_from_manifest(
        archive, manifest, int(item["block"]) - 1, tx["from"], target_block=int(item["block"])
    )
    case = Case(
        CASE_ID, "", "oracle", item["tx_hash"], block=int(item["block"]),
        tx_index=int(tx["transactionIndex"], 16),
        mainnet_gas=int(receipt["gasUsed"], 16),
        extra={"harm_spec": harm_spec},
        trace=(cache[item["tx_hash"].lower()].get("trace") or {}).get("tree"),
    )

    out_root = ROOT / "eval/results/e5_rcfh/dose_response/veth_amm_probe_v2"
    out_root.mkdir(parents=True, exist_ok=True)
    observations = []
    for idx, dose in enumerate(doses):
        run_id = f"e5-dose-veth-amm-{idx}"
        rows = run_necessity(
            case, [AmmReservePin(POOL, {SLOT: f"0x{dose:064x}"})],
            archive=archive, b2_context=context, run_id=run_id, timeout=900,
        )
        write_csv(rows, out_root / f"{idx:02d}.csv")
        observations.append({"dose_index": idx, "dose": str(dose), "rows": rows})

    artifact = {
        "schema_version": 1,
        "artifact": "e5-dose-response-diagnostic-probe",
        "corpus_id": "m4-frozen-20",
        "case_id": CASE_ID,
        "seam": {"type": "amm_reserve_read", "pool": POOL, "slot": SLOT},
        "dose_semantics": "linear interpolation from canonical pre-state storage to committed post-state storage",
        "claim_binding": "NOT_CLAIM_BOUND; VETH claim is flash-loan related",
        "revert_is_null_harm": True,
        "pre_state_value": str(pre),
        "post_state_value": str(post),
        "packed_layout": "reserve0[0:112] | reserve1[112:224] | timestamp[224:256]",
        "pre_components": {"reserve0": str(pre0), "reserve1": str(pre1), "timestamp": pre_timestamp},
        "post_components": {"reserve0": str(post0), "reserve1": str(post1), "timestamp": post_timestamp},
        "intervention_timestamp": pre_timestamp,
        "observations": observations,
    }
    (out_root / "result.json").write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"case_id": CASE_ID, "doses": len(doses), "out": str(out_root / "result.json")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
