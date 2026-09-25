"""Materialize the frozen Alkimiya/Morpho callback descriptor."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

ROOT = Path(__file__).resolve().parents[1]
CONTEXT = ROOT / "results/m6/dependency-contexts/alkimiya"
OUT = ROOT / "results/e4_causal_v4/alkimiya_morpho_trampoline_descriptor.json"
PROVIDER = "0xbbbbbbbbbb9cc5e90e3b3af64bdaf62c37eeffcb"
BORROWER = "0x80bf7db69556d9521c03461978b8fc731dbbd4e4"
PROVIDER_SELECTOR = "0xe0232b42"
CALLBACK_SELECTOR = "0x31f57072"


def walk(node, path, depth):
    if isinstance(node, dict):
        if str(node.get("input", "")).lower().startswith(CALLBACK_SELECTOR):
            yield path, depth, node
        for key, value in node.items():
            yield from walk(value, f"{path}/{key}", depth)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from walk(value, f"{path}/{index}", depth + (1 if path.endswith("/calls") else 0))


def main():
    doc = json.loads((CONTEXT / "poststates.json").read_text())
    matches = []
    # The frozen context stores the target call tree under calltrace/calls.
    def scan(node, path="", depth=-1):
        if isinstance(node, dict):
            if (str(node.get("input", "")).lower().startswith(CALLBACK_SELECTOR)
                    and node.get("from", "").lower() == PROVIDER
                    and node.get("to", "").lower() == BORROWER):
                matches.append((path, node))
            for k, v in node.items():
                scan(v, f"{path}/{k}", depth)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                scan(v, f"{path}/{i}", depth)
    scan(doc)
    if len(matches) != 1:
        raise SystemExit(f"expected one Morpho callback, found {len(matches)}")
    path, frame = matches[0]
    result = {
        "schema_version": "e4-causal-v4-morpho-trampoline-descriptor-v1",
        "status": "PASS",
        "provider": PROVIDER,
        "provider_selector": PROVIDER_SELECTOR,
        "provider_caller": BORROWER,
        "provider_depth": 1,
        "callback_to": BORROWER,
        "callback_selector": CALLBACK_SELECTOR,
        "callback_input": frame["input"],
        "callback_frame_path": path,
        "callback_calldata_source": str(CONTEXT / "poststates.json"),
        "same_calldata_required": True,
        "capital_transfer": "omitted_in_counterfactual",
        "proof_bound_context": str(CONTEXT),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
