"""Small fail-closed artifact store owned by the application boundary."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class RunExists(FileExistsError):
    """Raised when a caller attempts to overwrite an existing run."""


class ChecksumMismatch(ValueError):
    """Raised when an artifact differs from its recorded digest."""


class ArtifactStore:
    """Create immutable run directories below a caller-provided root."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def create_run(self, run_id: str, metadata: dict[str, Any]) -> Path:
        if not run_id or Path(run_id).name != run_id or run_id in {".", ".."}:
            raise ValueError("run_id must be a non-empty directory name")
        run_dir = self.root / run_id
        try:
            run_dir.mkdir(parents=True, exist_ok=False)
        except FileExistsError as exc:
            raise RunExists(str(run_dir)) from exc
        payload = {"schema_version": 1, "run_id": run_id, **metadata}
        self._write_new(run_dir / "run_metadata.json", payload)
        return run_dir

    def write_json(self, run_id: str, name: str, payload: Any) -> Path:
        path = self._new_path(run_id, name, ".json")
        self._write_new(path, payload)
        return path

    def checksum(self, run_id: str, name: str) -> str:
        path = self._path(run_id, name)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return digest

    def verify(self, run_id: str, name: str, expected_sha256: str) -> None:
        actual = self.checksum(run_id, name)
        if actual != expected_sha256:
            raise ChecksumMismatch(f"{name}: expected {expected_sha256}, got {actual}")

    def finalize(self, run_id: str, status: str = "complete") -> Path:
        """Close a run once, recording status and output checksums."""
        if status not in {"complete", "failed", "incomplete"}:
            raise ValueError("unsupported run status")
        run_dir = self.root / run_id
        if not run_dir.is_dir():
            raise FileNotFoundError(run_dir)
        status_path = run_dir / "run_status.json"
        if status_path.exists():
            raise RunExists(str(status_path))
        files = {
            str(path.relative_to(run_dir)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(run_dir.rglob("*"))
            if path.is_file() and path.name != "run_status.json"
        }
        payload = {
            "schema_version": 1,
            "run_id": run_id,
            "status": status,
            "finished_at_utc": datetime.now(timezone.utc).isoformat(),
            "artifacts": files,
        }
        self._write_new(status_path, payload)
        return status_path

    def require_complete(self, run_id: str) -> None:
        """Require a complete, uncorrupted run before downstream reading."""
        status_path = self.root / run_id / "run_status.json"
        if not status_path.is_file():
            raise ValueError(f"run has no final status: {run_id}")
        payload = json.loads(status_path.read_text(encoding="utf-8"))
        if payload.get("status") != "complete":
            raise ValueError(f"run is not complete: {run_id}")
        run_dir = self.root / run_id
        actual = {
            str(path.relative_to(run_dir))
            for path in run_dir.rglob("*")
            if path.is_file() and path.name != "run_status.json"
        }
        expected = set(payload.get("artifacts", {}))
        if actual != expected:
            raise ChecksumMismatch(
                f"artifact inventory differs: missing={sorted(expected - actual)}, "
                f"unexpected={sorted(actual - expected)}"
            )
        for name, expected in payload.get("artifacts", {}).items():
            self.verify(run_id, name, expected)

    def _new_path(self, run_id: str, name: str, suffix: str) -> Path:
        if not name or Path(name).name != name or not name.endswith(suffix):
            raise ValueError(f"artifact name must be a filename ending in {suffix}")
        if Path(run_id).name != run_id or not (self.root / run_id).is_dir():
            raise FileNotFoundError(self.root / run_id)
        if (self.root / run_id / "run_status.json").exists():
            raise RunExists(f"run is finalized: {self.root / run_id}")
        path = self.root / run_id / name
        if path.exists():
            raise RunExists(str(path))
        return path

    def _path(self, run_id: str, name: str) -> Path:
        if Path(run_id).name != run_id or not name or Path(name).is_absolute():
            raise ValueError("run_id and artifact name cannot contain path separators")
        run_dir = self.root / run_id
        path = (run_dir / name).resolve()
        if run_dir.resolve() not in path.parents:
            raise ValueError("artifact name escapes run directory")
        if not path.is_file():
            raise FileNotFoundError(path)
        return path

    @staticmethod
    def _write_new(path: Path, payload: Any) -> None:
        if path.exists():
            raise RunExists(str(path))
        path.write_text(
            # Do not sort keys: JSON permits numeric-looking keys only after
            # conversion to strings, and metric maps may intentionally use
            # float budget keys alongside descriptive fields.
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
