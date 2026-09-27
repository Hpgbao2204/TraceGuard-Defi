"""BlockScan (NeurIPS 2025) anomaly scores on CPU, following src_eth/detection.py of the public code.

Run in a separate environment with the authors' pins (Python 3.11, torch 2.1, transformers 4.32):

    python eval/revision/blockscan_score.py --code <BlockScan checkout> --assets <eth assets dir> \
        --txt <preprocessed_tx.txt> --out <scores.json>

The assets directory holds the authors' released ``model/rope_roberta`` and ``config/tokenizer``. The
score of a transaction is BlockScan's: randomly mask g% of its tokens (seed 42, in file order) and count
the masked tokens whose original id is not among the model's top-s predictions (g = 15, s = 3,
1,024 tokens). This file imports nothing from the project so it runs in that environment.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import types
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from torch.nn.functional import softmax


def load(code: Path, assets: Path):
    sys.modules.setdefault("xformers", types.ModuleType("xformers"))  # only used on the flash-attention path
    sys.modules.setdefault("xformers.ops", types.ModuleType("xformers.ops"))
    sys.modules["xformers"].ops = sys.modules["xformers.ops"]
    torch.cuda.get_device_capability = lambda *a, **k: (0, 0)  # CPU: plain attention, as on pre-A100 GPUs
    sys.path.insert(0, str(code))
    from src_eth.foundation_model import replace_roberta_attn
    from transformers import AutoConfig, AutoModelForMaskedLM, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(str(assets / "config" / "tokenizer"), use_fast=True)
    replace_roberta_attn(False, True)
    model_path = assets / "model" / "rope_roberta"
    model = AutoModelForMaskedLM.from_pretrained(str(model_path), config=AutoConfig.from_pretrained(str(model_path)))
    return model.eval(), tokenizer


@torch.no_grad()
def score_lines(lines, model, tokenizer, g=15, s=3, seq_len=1024):
    np.random.seed(42)
    out = []
    for data in lines:
        input_ids = tokenizer(data, return_tensors="pt", padding=True, truncation=True, max_length=seq_len)["input_ids"][0]
        padding_size = (8 - input_ids.size(0) % 8) % 8
        input_ids = F.pad(input_ids, (0, padding_size), "constant", 1)
        masked = []
        idxs = np.random.choice(np.arange(1, len(input_ids) - padding_size), size=int(len(input_ids) * g / 100),
                                replace=False)
        for idx in idxs:
            masked.append((idx, input_ids[idx].item()))
            input_ids[idx] = tokenizer.mask_token_id
        attention_mask = torch.ones(len(input_ids))
        if padding_size:
            attention_mask[-padding_size:] = 0
        logits = model(input_ids=input_ids.unsqueeze(0), attention_mask=attention_mask.unsqueeze(0)).logits
        count = 0
        for idx, orig in masked:
            _, pred = softmax(logits[0, idx], dim=0).topk(s)
            if orig not in pred:
                count += 1
        out.append({"score": count, "n_tokens": int(len(input_ids) - padding_size), "n_masked": len(masked)})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", type=Path, required=True)
    ap.add_argument("--assets", type=Path, required=True)
    ap.add_argument("--txt", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--threads", type=int, default=0)
    args = ap.parse_args()
    if args.threads:
        torch.set_num_threads(args.threads)
    model, tokenizer = load(args.code, args.assets)
    lines = args.txt.read_text(encoding="utf-8").splitlines()
    t0 = time.perf_counter()
    res = score_lines(lines, model, tokenizer)
    args.out.write_text(json.dumps({"scores": res, "seconds": time.perf_counter() - t0,
                                    "torch": torch.__version__}, indent=0), encoding="utf-8")
    print(f"scored {len(res)} transactions in {time.perf_counter() - t0:.0f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
