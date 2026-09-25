"""Compare verified-source compilation with the historical implementation code."""
from __future__ import annotations
import hashlib, json, shutil, subprocess, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "eval/exploratory/xloot_verified_source/etherscan_response.json"
OUT = ROOT / "eval/results/m6_xloot_source_identity_check.json"
HISTORICAL = "785c21acee0942a23ce1539d0a054f9e2a0d1f58e71a99fd10a0661da0c40853"

def main() -> int:
    result = json.loads(SOURCE.read_text())["result"][0]
    tree = json.loads(result["SourceCode"][1:-1])
    with tempfile.TemporaryDirectory(prefix="xloot-source-id-") as td:
        root = Path(td)
        for name, item in tree["sources"].items():
            path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(item["content"])
        (root / "foundry.toml").write_text("[profile.default]\nsolc_version='0.8.20'\noptimizer=true\noptimizer_runs=200\nevm_version='paris'\n")
        forge = shutil.which("forge")
        if not forge: raise SystemExit("forge executable not found")
        proc = subprocess.run([forge, "inspect", "contracts/Staking.sol:Staking", "deployedBytecode", "--root", str(root)], text=True, capture_output=True, timeout=180)
        bytecode = proc.stdout.strip() if proc.returncode == 0 else ""
    compiled = None
    if bytecode.startswith("0x") and shutil.which("cast"):
        hashed = subprocess.run([shutil.which("cast"), "keccak", bytecode], text=True, capture_output=True, timeout=60)
        compiled = hashed.stdout.strip().removeprefix("0x") if hashed.returncode == 0 else None
    payload = {"status": "PASS" if compiled == HISTORICAL else "SOURCE_COMPILE_MISMATCH", "historical_code_hash_keccak": HISTORICAL, "compiled_code_hash_keccak": compiled, "compiler": result["CompilerVersion"], "optimizer_runs": result["Runs"], "via_ir": False, "error": proc.stderr[-2000:] if proc.returncode else None}
    OUT.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2))
    return 0 if payload["status"] == "PASS" else 1

if __name__ == "__main__": raise SystemExit(main())
