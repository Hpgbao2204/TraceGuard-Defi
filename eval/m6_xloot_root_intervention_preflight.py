"""Build a proof-bound XLoot root-flaw intervention candidate."""
import hashlib, json
from pathlib import Path

SRC = Path("eval/results/m6/dependency-contexts/xlootstaking/poststates.json")
OUT = Path("eval/results/m6_xloot_root_intervention_preflight.json")
TARGET = "0xf9afb26a"

def find(n, depth=0):
    if n.get("input", "").startswith(TARGET):
        yield n, depth
    for c in n.get("calls", []) or []:
        yield from find(c, depth + 1)

data = json.loads(SRC.read_text())
matches = list(find(data[3]["calltrace"]))
if len(matches) != 2:
    raise SystemExit(f"expected proxy+implementation frames, got {len(matches)}")
node, depth = matches[0]
raw = bytes.fromhex(node["input"][10:])
off = int.from_bytes(raw[:32], "big")
length = int.from_bytes(raw[off:off+32], "big")
ids = [int.from_bytes(raw[off+32+i*32:off+64+i*32], "big") for i in range(length)]
unique = list(dict.fromkeys(ids))
body = bytearray(raw)
body[off:off+32] = len(unique).to_bytes(32, "big")
body = body[:off+32] + b"".join(x.to_bytes(32, "big") for x in unique)
mutated = "0x" + TARGET[2:] + body.hex()
result = {
    "status": "PREFLIGHT_READY_INTERNAL_CALLDATA_REWRITE_SEAM_AVAILABLE",
    "label": "NOT_PREREGISTERED — root-flaw semantic preflight only",
    "source_context": str(SRC),
    "target": {"selector": TARGET, "baseline_depth": depth, "frame_count": len(matches)},
    "root_flaw": "redeem(uint256[]) accepts repeated owned NFT IDs and re-counts rewards before advancing nextRedeem[id]",
    "baseline": {"array_length": length, "unique_ids": len(unique), "repeat_factor": length // len(unique), "ids": unique},
    "intervention": {"semantics": "deduplicate_uint256_array_preserve_first_occurrence", "mutated_array_length": len(unique), "mutated_calldata": mutated},
    "execution_seam": "CallIntervention now supports a strict internal input rewrite while preserving canonical child dispatch.",
    "next_required": "Freeze this semantic and descriptor, then run baseline/sham/deduplicated intervention under supplementary $5k only.",
}
result["mutated_calldata_sha256"] = hashlib.sha256(mutated.encode()).hexdigest()
OUT.write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps({"output": str(OUT), "status": result["status"], "array": [length, len(unique)]}, indent=2))
