"""BlockScan (NeurIPS 2025) reproduced on the frozen block-grouped split of RQ1 (review item: a recent baseline).

    python -m eval.revision.blockscan prepare    # traces -> BlockScan pre-tokenization text
    python -m eval.revision.blockscan score      # authors' pretrained model, in .cache/blockscan-venv
    python -m eval.revision.blockscan evaluate   # same threshold rule and metrics as Stage 1

Code: https://github.com/nuwuxian/BlockScan (checkout in .cache/blockscan). Assets: the authors' released
Ethereum model and tokenizer (Google Drive folder linked from their README, unpacked into
.cache/blockscan-dl/block_chain/eth). BlockScan is unsupervised: the pretrained model is used as released and
never sees our labels; only the threshold comes from our calibration partition.

Adapter. BlockScan reads a decoded call tree (func = selector, args and outputs as 32-byte words typed
address or data, logs with typed topics and data words). We build it from the callTracer tree in the trace
cache: the selector is the first four bytes of the input, arguments, outputs and log data are split into
32-byte words, and a word is typed ``address`` when its first twelve bytes are zero and its last twenty are a
plausible address (non-zero within the first four of them); addresses inside arguments, outputs and logs are
checksummed as in the authors' data. The authors' ``extract_function_calls`` and token normalization are then
applied unchanged (imported from their preprocess.py), including dropping out-of-vocabulary addresses.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
from pathlib import Path

import numpy as np

from eval.e1_common import average_precision, metrics_at_thresholds, select_fpr_thresholds
from eval.e1_robustness import _is_near_negative
from eval.e1_train import build_dataset
from eval.revision.stage1 import BUDGET, CACHE, COHORTS, ROOT, SPLIT, bootstrap_auprc

CODE = ROOT / ".cache" / "blockscan"
ASSETS = ROOT / ".cache" / "blockscan-dl" / "block_chain" / "eth"
VENV_PY = ROOT / ".cache" / "blockscan-venv" / "Scripts" / "python.exe"
WORK = ROOT / ".cache" / "revision" / "blockscan"


def _bs_preprocess():
    import sys
    import types
    if importlib.util.find_spec("tqdm") is None:  # imported by preprocess.py for progress bars only
        sys.modules["tqdm"] = types.SimpleNamespace(tqdm=lambda x, *a, **k: x)
    spec = importlib.util.spec_from_file_location("bs_preprocess", CODE / "src_eth" / "preprocess.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _checksum(addr: str) -> str:
    from eth_utils import to_checksum_address
    return to_checksum_address(addr)


def _words(hexdata: str | None) -> list[dict]:
    if not hexdata or hexdata in ("0x", "0X"):
        return []
    body = hexdata[2:] if hexdata.startswith(("0x", "0X")) else hexdata
    out = []
    for i in range(0, len(body), 64):
        w = body[i:i + 64]
        if len(w) == 64 and w[:24] == "0" * 24 and w[24:32] != "0" * 8:
            out.append({"type": "address", "data": _checksum("0x" + w[24:])})
        else:
            out.append({"type": "data", "data": "0x" + w})
    return out


def _int(x) -> int | None:
    if x is None:
        return None
    return int(x, 16) if isinstance(x, str) else int(x)


def to_blockscan(node: dict) -> dict:
    """callTracer node -> BlockScan decoded node."""
    inp = node.get("input") or "0x"
    out = {"type": node.get("type", "CALL"), "from": (node.get("from") or "").lower(),
           "to": (node.get("to") or "").lower(), "gas": _int(node.get("gas"))}
    if node.get("value") is not None:
        out["value"] = _int(node.get("value"))
    if len(inp) >= 10:
        out["func"] = inp[:10].lower()
        out["args"] = _words("0x" + inp[10:])
    outputs = _words(node.get("output"))
    if outputs:
        out["output"] = outputs
    if node.get("calls"):
        out["calls"] = [to_blockscan(c) for c in node["calls"]]
    logs = []
    for lg in node.get("logs") or []:
        topics = lg.get("topics") or []
        if not topics:
            continue
        logs.append({"address": (lg.get("address") or "").lower(),
                     "topics": [{"type": "data", "data": topics[0]}] + [_words(t)[0] for t in topics[1:] if _words(t)],
                     "data": _words(lg.get("data"))})
    if logs:
        out["logs"] = logs
    return out


def pretokenize(bs, tree: dict, reserved: set[str]) -> str:
    """The authors' write_all_traces for one transaction, with remove_oov=True."""
    trace = bs.extract_function_calls(to_blockscan(tree))
    for k, token in enumerate(trace):
        if bs.is_address(token) or bs.is_hash(token):
            if token not in reserved:
                trace[k] = "[OOV]"
        elif bs.is_decimal(token):
            trace[k] = bs.convert_decimal_to_hex_if_needed(token)
        elif bs.is_rare_hex(token):
            trace[k] = bs.pad_hex(token)
        elif bs.is_float(token):
            trace[k] = bs.convert_decimal_to_hex_if_needed(int(token))
    return " ".join(map(str, trace)).replace(" [OOV]", "")


def _split():
    return json.loads(SPLIT.read_text(encoding="utf-8"))["partitions"]


def cmd_prepare(_args) -> None:
    bs = _bs_preprocess()
    cfg = ASSETS / "config"
    reserved = set(["[CALL]", "[STATICCALL]", "[DELEGATECALL]", "[START]", "[END]", "[OOV]", "[INs]", "[OUTs]",
                    "[STATE]", "[LOG]", "[NONE]", "data", "address"]
                   + bs.read_txt(str(cfg / "top_20k_address.txt")) + bs.read_txt(str(cfg / "top_20k_hash.txt")))
    part = _split()
    wanted = set(part["calibration"]) | set(part["test"])
    trees = {}
    with CACHE.open(encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r["tx_hash"] in wanted:
                trees[r["tx_hash"]] = (r.get("trace") or {}).get("tree")
    order = list(part["calibration"]) + list(part["test"])
    missing = [h for h in order if not trees.get(h)]
    WORK.mkdir(parents=True, exist_ok=True)
    lines = [pretokenize(bs, trees[h], reserved) if trees.get(h) else "" for h in order]
    (WORK / "preprocessed_tx.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (WORK / "tx_hashes.json").write_text(json.dumps(order), encoding="utf-8")
    print(f"wrote {len(order)} transactions ({len(missing)} without a call tree)")


def cmd_score(args) -> None:
    subprocess.run([str(VENV_PY), str(ROOT / "eval" / "revision" / "blockscan_score.py"), "--code", str(CODE),
                    "--assets", str(ASSETS), "--txt", str(WORK / "preprocessed_tx.txt"),
                    "--out", str(WORK / "scores.json"), "--threads", str(args.threads)], check=True)


def cmd_evaluate(_args) -> None:
    ds = build_dataset(CACHE)
    by_hash = {r["tx_hash"]: r for r in ds["rows"]}
    order = json.loads((WORK / "tx_hashes.json").read_text(encoding="utf-8"))
    raw = json.loads((WORK / "scores.json").read_text(encoding="utf-8"))["scores"]
    score = {h: float(r["score"]) for h, r in zip(order, raw)}
    part = _split()
    cal, test = list(part["calibration"]), list(part["test"])
    y_cal = np.array([by_hash[h]["label"] == "attack" for h in cal], dtype=float)
    y = np.array([by_hash[h]["label"] == "attack" for h in test], dtype=float)
    s_cal = np.array([score[h] for h in cal])
    s = np.array([score[h] for h in test])
    thr = select_fpr_thresholds(y_cal, s_cal, budgets=(BUDGET,))
    m = metrics_at_thresholds(y, s, thr, budgets=(BUDGET,))
    op = m[BUDGET]
    cohorts = json.loads(COHORTS.read_text(encoding="utf-8"))
    idx = {h: i for i, h in enumerate(test)}
    coh = {}
    for name, key in (("ordinary", "ordinary_negative_test"), ("near_negative", "near_negative_test")):
        sel = [idx[h] for h in cohorts["positive_test"] + cohorts[key]]
        coh[name] = {"auprc": average_precision(y[sel], s[sel]), "auprc_ci95": bootstrap_auprc(y[sel], s[sel]),
                     "fp": int(((s[sel] >= thr[BUDGET]) & (y[sel] == 0)).sum()), "n_neg": int((y[sel] == 0).sum())}
    # normalized variant (count / masked tokens): BlockScan's raw count grows with trace length
    frac = {h: r["score"] / max(r["n_masked"], 1) for h, r in zip(order, raw)}
    s_n = np.array([frac[h] for h in test])
    thr_n = select_fpr_thresholds(y_cal, np.array([frac[h] for h in cal]), budgets=(BUDGET,))
    m_n = metrics_at_thresholds(y, s_n, thr_n, budgets=(BUDGET,))
    near = {h for h in test if by_hash[h]["label"] != "attack" and _is_near_negative(by_hash[h]["row"])}
    res = {
        "n_cal": len(cal), "n_test": len(test), "n_pos_test": int(y.sum()), "tau": thr[BUDGET],
        "auprc": m["auc_pr"], "auprc_ci95": bootstrap_auprc(y, s),
        "recall": op["recall"], "precision": op["precision"], "fpr": op["realized_fpr"], "tp": op["tp"], "fp": op["fp"],
        "fp_near": int(sum(1 for h, sc in zip(test, s) if h in near and sc >= thr[BUDGET])),
        "cohorts": coh,
        "normalized": {"auprc": m_n["auc_pr"], "auprc_ci95": bootstrap_auprc(y, s_n),
                       "recall": m_n[BUDGET]["recall"], "fpr": m_n[BUDGET]["realized_fpr"]},
        "score_median": {"attack": float(np.median(s[y == 1])), "benign": float(np.median(s[y == 0]))},
        "seconds": json.loads((WORK / "scores.json").read_text(encoding="utf-8")).get("seconds"),
    }
    (WORK / "evaluation.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps(res, indent=1))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("prepare")
    sc = sub.add_parser("score")
    sc.add_argument("--threads", type=int, default=0)
    sub.add_parser("evaluate")
    args = ap.parse_args()
    {"prepare": cmd_prepare, "score": cmd_score, "evaluate": cmd_evaluate}[args.cmd](args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
