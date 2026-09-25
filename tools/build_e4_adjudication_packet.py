"""Build a vote-preserving E4 adjudication worksheet.

The output is an input for a human adjudicator, not a final sidecar.  No
decision is inferred and no reviewer row is modified.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUBMISSIONS = ROOT / "corpus/annotations/review_submissions"
OUT = ROOT / "corpus/annotations/adjudication/e4_adjudication_input.jsonl"


def load(path: Path) -> dict[str, dict]:
    return {row["case_id"]: row for row in
            (json.loads(line) for line in path.read_text().splitlines() if line.strip())}


def main() -> None:
    a_path = SUBMISSIONS / "e4_reviewer_a.jsonl"
    b_path = SUBMISSIONS / "e4_reviewer_b.jsonl"
    a, b = load(a_path), load(b_path)
    if set(a) != set(b) or len(a) != 20:
        raise ValueError("E4 submissions must contain the same 20 case IDs")
    records = []
    for case_id in a:
        left, right = a[case_id], b[case_id]
        immutable = {
            "case_id": case_id,
            "tx_hash": left["tx_hash"],
            "block": left["block"],
            "fixed_set_sha256": left["fixed_set_sha256"],
            "reviewer_votes": [left, right],
            "adjudication": {"status": "pending", "adjudicator": "", "note": ""},
        }
        if left["tx_hash"].lower() != right["tx_hash"].lower() or left["block"] != right["block"]:
            raise ValueError(f"identity mismatch for {case_id}")
        records.append(immutable)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                                for row in records), encoding="utf-8", newline="\n")
    print(json.dumps({
        "cases": len(records),
        "reviewer_a_sha256": hashlib.sha256(a_path.read_bytes()).hexdigest(),
        "reviewer_b_sha256": hashlib.sha256(b_path.read_bytes()).hexdigest(),
        "output": str(OUT.relative_to(ROOT)),
    }, indent=2))


if __name__ == "__main__":
    main()
