import tempfile
import unittest
from pathlib import Path

from core.artifacts import ArtifactStore
from tools.build_release_manifest_v2 import build


class ReleaseManifestProvenanceTests(unittest.TestCase):
    def test_unfinalized_selected_run_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = root / "eval/results/runs/e1-grouped-v2-freeze-20260909-r2"
            store = ArtifactStore(root / "eval/results/runs")
            store.create_run("e1-grouped-v2-freeze-20260909-r2", {})
            store.write_json("e1-grouped-v2-freeze-20260909-r2",
                             "split_manifest.json", {"views": []})
            with self.assertRaises(ValueError) as error:
                build(root, root / "manifest.json")
            self.assertIn("no final status", str(error.exception))
            self.assertTrue(run.is_dir())


if __name__ == "__main__":
    unittest.main()
