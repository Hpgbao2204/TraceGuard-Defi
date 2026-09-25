"""Materialize formal Reviewer-C adjudication without changing raw votes."""
from __future__ import annotations
import hashlib, json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "corpus/annotations/review_bundles_supplementary"
OUT = BASE / "m6_supplementary_adjudication_reviewer_c_v2.jsonl"
FIELDS = ("eligibility", "mechanism_summary", "root_cause", "flash_loan_role",
          "oracle_subtype", "protected_entities", "harm_assets", "lmin_usd",
          "valuation_source", "evidence", "label_confidence", "reviewer_note")

def rows(path):
    return {r["case_id"]: r for r in (json.loads(x) for x in path.read_text().splitlines() if x.strip())}

def parse(value):
    if isinstance(value, (list, dict)): return value
    if isinstance(value, str) and value.strip():
        try: return json.loads(value)
        except json.JSONDecodeError: return value
    return []

def canonical_factor(value):
    mapping = {"f_logic": "f_other", "f_access": "f_auth", "f_arithmetic": "f_other"}
    vals = value if isinstance(value, list) else [x.strip() for x in re.split(r"[, +]+", str(value or "")) if x.strip()]
    return [mapping.get(x, x) for x in vals]

def main():
    a = rows(BASE / "reviewer_a_new.jsonl")
    b = rows(BASE / "reviewer_b_new.jsonl")
    c = rows(BASE / "reviewer_c.jsonl")
    output = []
    for cid in sorted(c):
        adjudicator = c[cid]
        final = {k: parse(adjudicator.get(k)) if k in ("protected_entities", "harm_assets", "evidence") else adjudicator.get(k) for k in FIELDS}
        final["root_cause_gt"] = [f for f in canonical_factor(adjudicator.get("root_cause"))
                                   if not (f == "f_fl" and adjudicator.get("flash_loan_role") != "causal")]
        final["reviewer_votes"] = [{"reviewer": "reviewer_a", **{k: a[cid].get(k) for k in FIELDS}},
                                    {"reviewer": "reviewer_b", **{k: b[cid].get(k) for k in FIELDS}}]
        final["adjudication"] = {"status": "adjudicated", "adjudicator": "Reviewer C",
                                 "source_record": cid, "note": adjudicator.get("reviewer_note", "")}
        final.update({"schema_version": 1, "reviewer": "reviewer_c", "case_id": cid,
                      "tx_hash": adjudicator["tx_hash"],
                      "packet_sha256": adjudicator["packet_sha256"]})
        output.append(final)
    OUT.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in output))
    print(json.dumps({"records": len(output), "sha256": hashlib.sha256(OUT.read_bytes()).hexdigest(),
                      "release_positive": 0, "out": str(OUT)}, indent=2))

if __name__ == "__main__": main()
