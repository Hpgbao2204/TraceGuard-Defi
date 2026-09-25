"""Validate callback postconditions for the Alkimiya Morpho trampoline runs."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results/e4_causal_v4/alkimiya_morpho_trampoline_postconditions.json"
DESC = json.loads((ROOT / "results/e4_causal_v4/alkimiya_morpho_trampoline_descriptor.json").read_text())


def frames(path):
    doc = json.loads(Path(path).read_text())
    doc = doc.get("runner_output", doc)
    return doc.get("per_tx", [{}])[0].get("call_trace", [])


def intervention(path):
    doc = json.loads(Path(path).read_text())
    doc = doc.get("runner_output", doc)
    return doc.get("per_tx", [{}])[0].get("call_intervention", {})


def find(frames_, selector):
    return [f for f in frames_ if str(f.get("input", "")).lower().startswith(selector)]


def main():
    canonical = frames("/tmp/alkimiya-canonical.json")
    rows = []
    for mode in ("sham", "counterfactual"):
        path = ROOT / f"results/e4_causal_v4/alkimiya_morpho_trampoline_{mode}.json"
        current = frames(path)
        evidence = intervention(path)
        expected = find(canonical, DESC["callback_selector"])
        actual = find(current, DESC["callback_selector"])
        expected_one = expected[0] if expected else {}
        actual_one = actual[0] if actual else evidence
        checks = {
            "callback_count": evidence.get("callback_attempted") is True,
            "callback_caller": actual_one.get("from", actual_one.get("callback_caller", "")).lower() == DESC["provider"].lower(),
            "callback_callee": actual_one.get("to", actual_one.get("callback_to", "")).lower() == DESC["callback_to"].lower(),
            "callback_input": actual_one.get("input", actual_one.get("callback_input")) == DESC["callback_input"],
            "historical_callback_input": expected_one.get("input") == DESC["callback_input"],
        }
        rows.append({"mode": mode, "checks": checks,
                     "all_postconditions_pass": all(checks.values()),
                     "observed_callback_count": len(actual),
                     "historical_callback_count": len(expected),
                     "observed_frame": actual_one})
    result = {
        "schema_version": "e4-causal-v4-morpho-trampoline-postconditions-v1",
        "status": "PASS" if all(r["all_postconditions_pass"] for r in rows) else "FAIL",
        "causal_verdict": None,
        "descriptor": str(ROOT / "results/e4_causal_v4/alkimiya_morpho_trampoline_descriptor.json"),
        "canonical_source": "/tmp/alkimiya-canonical.json",
        "rows": rows,
        "note": "Depth is validated by the strict intervention record; callback frames do not carry depth in all serialized traces.",
    }
    OUT.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
