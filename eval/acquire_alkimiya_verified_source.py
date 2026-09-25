"""Acquire Etherscan-verified SilicaPools source for a reproducible patch build."""
from __future__ import annotations
import argparse, html, json, os, re, subprocess
from pathlib import Path

ADDRESS = "0xf3f84ce038442ae4c4dcb6a8ca8bacd7f28c9bde"
URL = f"https://etherscan.io/address/{ADDRESS}#code"

def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--tree", type=Path, required=True)
    ap.add_argument("--meta", type=Path, required=True); a = ap.parse_args()
    key = os.environ.get("ETHERSCAN")
    if key:
        api = f"https://api.etherscan.io/v2/api?chainid=1&module=contract&action=getsourcecode&address={ADDRESS}&apikey={key}"
        response = subprocess.check_output(["curl", "--compressed", "-A", "Mozilla/5.0", "-LsS", "--max-time", "45", api], text=True)
        payload = json.loads(response)
        row = payload.get("result", [{}])[0]
        encoded = row.get("SourceCode", "")
        if encoded.startswith("{{") and encoded.endswith("}}"):
            encoded = encoded[1:-1]
        try:
            tree = json.loads(encoded) if encoded.startswith("{") else {"contracts/SilicaPools.sol": encoded}
        except json.JSONDecodeError as exc:
            raise SystemExit(f"Etherscan SourceCode JSON invalid: {exc}")
        if "sources" in tree:
            tree = tree["sources"]
        tree = {name: (value.get("content", "") if isinstance(value, dict) else value) for name, value in tree.items()}
    else:
        raw = subprocess.check_output(["curl", "-L", "--fail", "--max-time", "30", URL], text=True)
        files = re.findall(r"data-cname='([^']+)' data-csource='(.*?)'", raw, re.S)
        tree = {name: html.unescape(content) for name, content in files}
    if "contracts/SilicaPools.sol" not in tree:
        raise SystemExit("SilicaPools.sol missing from verified source tree")
    source = tree["contracts/SilicaPools.sol"]
    a.tree.mkdir(parents=True, exist_ok=True)
    for name, content in tree.items():
        dest = a.tree / name; dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(source, encoding="utf-8")
    if "contract SilicaPools" not in source or "function collateralizedMint" not in source:
        raise SystemExit("extracted source is not the complete SilicaPools source")
    meta = {"address": ADDRESS, "url": URL, "source_sha256": __import__("hashlib").sha256(source.encode()).hexdigest(), "file_count": len(tree), "source_tree": str(a.tree), "compiler": "v0.8.20+commit.a1b79de6", "optimizer": True, "runs": 200, "viaIR": True, "evmVersion": "paris", "source_start_marker": "contract SilicaPools"}
    a.meta.parent.mkdir(parents=True, exist_ok=True); a.meta.write_text(json.dumps(meta, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(meta, indent=2)); return 0
if __name__ == "__main__": raise SystemExit(main())
