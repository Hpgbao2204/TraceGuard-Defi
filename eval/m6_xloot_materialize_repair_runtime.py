"""Materialize the source-faithful XLoot accounting repair as a preflight."""
from __future__ import annotations
import hashlib, json, shutil, subprocess, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_JSON = ROOT / "eval/exploratory/xloot_verified_source/etherscan_response.json"
OUT = ROOT / "eval/results/m6_xloot_accounting_repair_runtime_preflight.json"
BYTECODE_OUT = ROOT / "eval/results/m6_xloot_accounting_repair_runtime.hex"
ARTIFACT_OUT = ROOT / "eval/results/m6_xloot_accounting_repair_runtime_artifact.json"
OLD = """                if (\n                    $.xloot.nextRedeem[id] > 0 &&\n                    $.xloot.nextRedeem[id] < $.nextEpocId\n                ) {"""
HELPER_ANCHOR = "    function _redeemable(\n"
HELPER = """    function _xlootSeenWords(uint256[] memory xloots) internal pure returns (uint256[] memory words) {\n        uint256 maxId;\n        for (uint256 k = 0; k < xloots.length; k++) {\n            if (xloots[k] > maxId) maxId = xloots[k];\n        }\n        words = new uint256[](maxId / 256 + 1);\n    }\n\n    function _xlootMarkSeen(uint256[] memory words, uint256 id) internal pure returns (bool duplicate) {\n        uint256 word = id / 256;\n        uint256 bit = uint256(1) << (id % 256);\n        duplicate = (words[word] & bit) != 0;\n        words[word] |= bit;\n    }\n\n"""
NEW = """                bool duplicate = false;\n                for (uint256 k = 0; k < i; k++) {\n                    if (xloots[k] == id) { duplicate = true; break; }\n                }\n                if (!duplicate &&\n                    $.xloot.nextRedeem[id] > 0 &&\n                    $.xloot.nextRedeem[id] < $.nextEpocId\n                ) {"""
NEW = """                if (!_xlootMarkSeen(seenWords, id) &&\n                    $.xloot.nextRedeem[id] > 0 &&\n                    $.xloot.nextRedeem[id] < $.nextEpocId\n                ) {"""

def main() -> int:
    payload = json.loads(SOURCE_JSON.read_text())
    result = payload["result"][0]
    tree = json.loads(result["SourceCode"][1:-1])
    source = tree["sources"]["contracts/Staking.sol"]["content"]
    if source.count(OLD) != 1:
        raise SystemExit("repair anchor is not unique")
    if source.count(HELPER_ANCHOR) != 1:
        raise SystemExit("helper anchor is not unique")
    loop_anchor = """        if (xloots.length > 0) {
            for (uint256 i = 0; i < xloots.length; i++) {
                uint256 id = xloots[i];"""
    if source.count(loop_anchor) != 1:
        raise SystemExit("xloot repair loop anchor is not unique")
    patched = source.replace(HELPER_ANCHOR, HELPER + HELPER_ANCHOR)
    patched = patched.replace(loop_anchor, """        if (xloots.length > 0) {
            uint256[] memory seenWords = _xlootSeenWords(xloots);
            for (uint256 i = 0; i < xloots.length; i++) {
                uint256 id = xloots[i];""")
    patched = patched.replace(OLD, NEW)
    with tempfile.TemporaryDirectory(prefix="xloot-repair-") as td:
        root = Path(td)
        for name, item in tree["sources"].items():
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(patched if name == "contracts/Staking.sol" else item["content"])
        (root / "foundry.toml").write_text("[profile.default]\nsolc_version='0.8.20'\noptimizer=true\noptimizer_runs=200\nvia_ir=true\nevm_version='paris'\n")
        forge = shutil.which("forge")
        if not forge:
            status, error, runtime_hash = "BLOCKED_FORGE_MISSING", "forge executable not found", None
        else:
            proc = subprocess.run([forge, "build", "--root", str(root), "--silent"], text=True, capture_output=True, timeout=180)
            status = "COMPILED" if proc.returncode == 0 else "COMPILE_FAILED"
            error = (proc.stderr or proc.stdout)[-4000:] if proc.returncode else None
            runtime_hash = None
            runtime_hex = None
            if proc.returncode == 0:
                for artifact in (root / "out").rglob("*.json"):
                    try:
                        obj = json.loads(artifact.read_text())
                        bytecode = obj.get("deployedBytecode", {}).get("object", "")
                        if bytecode:
                            runtime_hex = bytecode
                            runtime_hash = hashlib.sha256(bytes.fromhex(bytecode)).hexdigest()
                            break
                    except (OSError, ValueError, json.JSONDecodeError):
                        continue
                if runtime_hash is None:
                    inspect = subprocess.run(
                        [forge, "inspect", "contracts/Staking.sol:Staking", "deployedBytecode", "--root", str(root)],
                        text=True, capture_output=True, timeout=60,
                    )
                    if inspect.returncode == 0:
                        text = inspect.stdout.strip()
                        if text.startswith("0x"):
                            runtime_hex = text[2:]
                            runtime_hash = hashlib.sha256(bytes.fromhex(runtime_hex)).hexdigest()
        if runtime_hex:
            BYTECODE_OUT.write_text("0x" + runtime_hex + "\n")
            ARTIFACT_OUT.write_text(json.dumps({"deployedBytecode": {"object": "0x" + runtime_hex}}, indent=2) + "\n")
    OUT.write_text(json.dumps({
        "schema_version": 1, "status": status, "case_id": "xlootstaking",
        "repair": "preserve calldata length/order and owner checks; suppress duplicate reward accounting",
        "source_basis": str(SOURCE_JSON.relative_to(ROOT)),
        "compiler_metadata": {"version": result["CompilerVersion"], "optimizer_runs": result["Runs"], "via_ir": True},
        "runtime_sha256": runtime_hash, "error": error,
        "runtime_artifact": str(BYTECODE_OUT.relative_to(ROOT)) if runtime_hex else None,
        "artifact_json": str(ARTIFACT_OUT.relative_to(ROOT)) if runtime_hex else None,
        "replay_authorized": False, "causal_verdict": None,
    }, indent=2) + "\n")
    print(OUT)
    return 0 if status == "COMPILED" else 1

if __name__ == "__main__":
    raise SystemExit(main())
