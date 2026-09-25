from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.artifacts import ArtifactStore, ChecksumMismatch, RunExists


class ArtifactStoreTests(unittest.TestCase):
    def test_run_and_artifact_cannot_be_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(Path(directory))
            store.create_run("run-a", {"experiment": "test"})
            with self.assertRaises(RunExists):
                store.create_run("run-a", {})
            store.write_json("run-a", "result.json", {"value": 1})
            with self.assertRaises(RunExists):
                store.write_json("run-a", "result.json", {"value": 2})

    def test_checksum_detects_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(Path(directory))
            store.create_run("run-a", {})
            path = store.write_json("run-a", "result.json", {"value": 1})
            digest = store.checksum("run-a", "result.json")
            store.verify("run-a", "result.json", digest)
            path.write_text("corrupted\n", encoding="utf-8")
            with self.assertRaises(ChecksumMismatch):
                store.verify("run-a", "result.json", digest)

    def test_path_traversal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(Path(directory))
            with self.assertRaises(ValueError):
                store.create_run("../escape", {})

    def test_finalize_records_status_and_detects_corruption(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(Path(directory))
            store.create_run("run-a", {})
            path = store.write_json("run-a", "result.json", {"value": 1})
            store.finalize("run-a")
            store.require_complete("run-a")
            path.write_text("corrupted\n", encoding="utf-8")
            with self.assertRaises(ChecksumMismatch):
                store.require_complete("run-a")

    def test_finalized_run_rejects_new_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(Path(directory))
            store.create_run("run-a", {})
            store.finalize("run-a")
            with self.assertRaises(RunExists):
                store.write_json("run-a", "late.json", {"value": 1})

    def test_finalize_covers_nested_files_and_rejects_added_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(Path(directory))
            run_dir = store.create_run("run-a", {})
            nested = run_dir / "outputs" / "result.json"
            nested.parent.mkdir()
            nested.write_text("{}", encoding="utf-8")
            store.finalize("run-a")
            store.require_complete("run-a")
            (run_dir / "outputs" / "unexpected.json").write_text("{}", encoding="utf-8")
            with self.assertRaises(ChecksumMismatch):
                store.require_complete("run-a")


if __name__ == "__main__":
    unittest.main()
