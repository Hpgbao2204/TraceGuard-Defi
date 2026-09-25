import csv
import json
from pathlib import Path

from corpus.scripts.build_review_packets import run


def test_review_packets_support_external_output_dir(tmp_path: Path) -> None:
    fixed = tmp_path / "fixed.json"
    fixed.write_text(json.dumps({"cases": [
        {"case_id": f"case-{i}", "tx_hash": "0x" + f"{i:064x}", "block": i}
        for i in range(20)
    ]}), encoding="utf-8")
    queue = tmp_path / "queue.csv"
    with queue.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "attack_case_id", "attack_tx_hash", "attack_block",
            "candidate_tx_hash", "candidate_block", "window_blocks",
            "within_window",
        ])
        writer.writeheader()
        writer.writerow({
            "attack_case_id": "case-0",
            "attack_tx_hash": "0x" + "a" * 64,
            "attack_block": "1",
            "candidate_tx_hash": "0x" + "b" * 64,
            "candidate_block": "2",
            "window_blocks": "216000",
            "within_window": "True",
        })
    out = tmp_path / "packets"

    result = run(fixed, queue, out)

    assert result["hard_negative_rows_per_reviewer"] == 1
    assert all(Path(path).is_absolute() for path in result["packets"])
    assert len((out / "hard_negatives_reviewer_a.jsonl").read_text().splitlines()) == 1
    packet_manifest = json.loads((out / "packet_manifest.json").read_text())
    assert packet_manifest["schema_version"] == 2
    assert len(packet_manifest["fixed_set_sha256"]) == 64
    assert len(packet_manifest["packet_hashes"]["hard_negatives_reviewer_a"]) == 64
    packet_row = json.loads((out / "e4_reviewer_a.jsonl").read_text().splitlines()[0])
    assert packet_row["fixed_set_sha256"] == packet_manifest["fixed_set_sha256"]
    assert packet_row["packet_sha256"] == packet_manifest["packet_hashes"]["e4_reviewer_a"]

    first_bytes = {
        path.name: path.read_bytes() for path in out.iterdir() if path.is_file()
    }
    run(fixed, queue, out)
    assert first_bytes == {
        path.name: path.read_bytes() for path in out.iterdir() if path.is_file()
    }
