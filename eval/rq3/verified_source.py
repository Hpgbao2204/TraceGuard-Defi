"""Fetch Etherscan-verified source for a contract into .cache/verified/<address>/ (local only).

    python -m eval.rq3.verified_source 0xec9c8e3b...

Uses the ETHERSCAN key from .env (never printed) and writes every source file plus meta.json with the
compiler version and settings reported by Etherscan.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

from core.env import load_dotenv

ROOT = Path(__file__).resolve().parents[2]


def fetch(address: str) -> Path:
    load_dotenv()
    key = os.environ.get("ETHERSCAN") or os.environ.get("ETHERSCAN_API_KEY") or ""
    url = ("https://api.etherscan.io/v2/api?chainid=1&module=contract&action=getsourcecode"
           f"&address={address}&apikey={key}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        row = json.loads(resp.read())["result"][0]
    out = ROOT / ".cache" / "verified" / address.lower()
    out.mkdir(parents=True, exist_ok=True)
    src = row.get("SourceCode", "")
    if src.startswith("{{") and src.endswith("}}"):
        src = src[1:-1]
    try:
        tree = json.loads(src) if src.startswith("{") else {f"{row.get('ContractName') or 'Main'}.sol": src}
    except json.JSONDecodeError:
        tree = {f"{row.get('ContractName') or 'Main'}.sol": src}
    settings = tree.get("settings") if isinstance(tree, dict) else None
    files = tree.get("sources", tree)
    for name, value in files.items():
        dest = out / "src" / name.lstrip("/")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(value.get("content", "") if isinstance(value, dict) else value, encoding="utf-8")
    meta = {k: row.get(k) for k in ("ContractName", "CompilerVersion", "OptimizationUsed", "Runs", "EVMVersion",
                                   "Proxy", "Implementation")}
    meta["settings"] = settings
    meta["files"] = sorted(files)
    (out / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return out


if __name__ == "__main__":
    for a in sys.argv[1:]:
        p = fetch(a)
        m = json.loads((p / "meta.json").read_text(encoding="utf-8"))
        print(a, m["ContractName"], m["CompilerVersion"], len(m["files"]), "files ->", p)
