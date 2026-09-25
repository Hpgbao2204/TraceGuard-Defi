"""Create the preregistered minimal arithmetic guard source variant."""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path

MARKER = "sState.sharesMinted += uint128(shares);"
REPLACEMENT = "if (shares > type(uint128).max) revert SilicaPools__SharesTooLarge();\n        sState.sharesMinted += uint128(shares);"

def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument("--source",type=Path,required=True); ap.add_argument("--out",type=Path,required=True); ap.add_argument("--manifest",type=Path,required=True); ap.add_argument("--tree-out",type=Path); a=ap.parse_args()
    s=a.source.read_text(encoding="utf-8")
    if s.count(MARKER) != 1: raise SystemExit(f"expected one target marker, found {s.count(MARKER)}")
    if "error SilicaPools__SharesTooLarge" not in s:
        anchor="contract SilicaPools is ISilicaPools, ERC1155, EIP712, Ownable2Step, ReentrancyGuard {"
        s=s.replace(anchor, anchor+"\n    error SilicaPools__SharesTooLarge();", 1)
    s=s.replace(MARKER, REPLACEMENT, 1)
    a.out.parent.mkdir(parents=True,exist_ok=True); a.out.write_text(s,encoding="utf-8")
    if a.tree_out:
        a.tree_out.parent.mkdir(parents=True, exist_ok=True); a.tree_out.write_text(s, encoding="utf-8")
    m={"schema_version":1,"intervention":"checked_uint128_shares_guard","source":str(a.source),"source_sha256":hashlib.sha256(a.source.read_bytes()).hexdigest(),"patched_source":str(a.out),"patched_source_sha256":hashlib.sha256(s.encode()).hexdigest(),"target_address":"0xf3f84ce038442ae4c4dcb6a8ca8bacd7f28c9bde","selector":"0x71e109d4","change":"reject shares > uint128.max before sharesMinted downcast","abi_storage_assumption":"unchanged source contract and storage layout","stack_or_calldata_patch":False}
    a.manifest.parent.mkdir(parents=True,exist_ok=True); a.manifest.write_text(json.dumps(m,indent=2)+"\n",encoding="utf-8"); print(json.dumps(m,indent=2)); return 0
if __name__ == "__main__": raise SystemExit(main())
