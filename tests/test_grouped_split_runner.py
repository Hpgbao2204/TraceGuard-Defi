from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from eval.e1_grouped_v2 import freeze


class GroupedSplitRunnerTests(unittest.TestCase):
    def test_freeze_writes_new_run_with_input_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / "cache.jsonl"
            # The runner expects the cache schema; use a tiny valid cache and
            # point runs outside the repository only for the writer contract.
            rows = [
                {"tx_hash": "0x1", "label": "attack", "status": True, "block": 1, "trace": {}},
                {"tx_hash": "0x2", "label": "benign", "status": True, "block": 2, "trace": {}},
                {"tx_hash": "0x3", "label": "benign", "status": True, "block": 3, "trace": {}},
            ]
            cache.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
            run_dir = freeze(cache, root / "runs", "split-run")
            metadata = json.loads((run_dir / "run_metadata.json").read_text())
            split = json.loads((run_dir / "split_manifest.json").read_text())
            self.assertEqual(metadata["run_id"], "split-run")
            self.assertEqual(metadata["inputs"]["row_count"], 3)
            self.assertEqual(split["protocol_version"], "screening-grouped-v2")
            self.assertEqual(split["feature_contract_version"], "screening-grouped-v2-4view")
            self.assertEqual(split["views"], ["call_structure", "token_flow", "state_delta", "economic"])


if __name__ == "__main__":
    unittest.main()
