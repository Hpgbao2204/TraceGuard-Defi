"""Merge parallel acquisition chunks without changing case content."""
import glob, json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "eval/results/e5_rcfh/defihacklabs_replay_acquisition.json"
def main():
    paths = sorted(glob.glob("/tmp/defihacklabs_acq_*.json"))
    rows = []
    for p in paths: rows.extend(json.loads(Path(p).read_text())["cases"])
    rows.sort(key=lambda r: r["candidate_id"])
    assert len(rows) == 80 and len({r["candidate_id"] for r in rows}) == 80
    summary = {}
    for r in rows: summary[r["status"]] = summary.get(r["status"], 0) + 1
    out = {"schema_version": 1, "artifact": "defihacklabs-replay-acquisition-v1", "source_artifact": "eval/results/e5_rcfh/defihacklabs_t0_candidate_pool.json", "parallel_chunks": [[0,20],[20,40],[40,60],[60,80]], "rpc_role": "archive_transaction_metadata_only", "cases": rows, "summary": summary, "next": "run B2 only for READY_FOR_B2; no missing/error case is treated as NO_HARM"}
    OUT.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"chunks": len(paths), "cases": len(rows), "summary": summary}, indent=2))
if __name__ == "__main__": main()
