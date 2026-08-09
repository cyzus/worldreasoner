"""Create immutable SQLite dataset releases with reproducibility manifests."""

import hashlib
import json
import re
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


MANIFEST_SCHEMA_VERSION = "2"
_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class DatasetVersionService:
    """Build versioned database snapshots using SQLite's backup API."""

    def __init__(self, versions_dir: Path) -> None:
        self.versions_dir = versions_dir

    def create_release(
        self,
        source_db: Path,
        version: str,
        parent_version: Optional[str] = None,
        operations: Optional[List[str]] = None,
        overwrite: bool = False,
    ) -> Dict[str, Any]:
        """Create a consistent database snapshot and write its manifest."""
        directory_name = self._directory_name(version)
        if not source_db.exists():
            raise FileNotFoundError(f"Source database not found: {source_db}")
        release_dir = self.versions_dir / directory_name
        release_dir.mkdir(parents=True, exist_ok=True)
        target_db = release_dir / "worldreasoner.db"
        manifest_path = release_dir / "manifest.json"
        if (target_db.exists() or manifest_path.exists()) and not overwrite:
            raise FileExistsError(
                f"Release {version} already exists; pass overwrite=True to replace it"
            )

        self._sqlite_backup(source_db, target_db)
        manifest = self._build_manifest(
            db_path=target_db,
            version=version,
            parent_version=parent_version,
            operations=operations or [],
            source_db=source_db,
        )
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return manifest

    def refresh_manifest(
        self,
        version: str,
        operations: Optional[List[str]] = None,
        llm_passes: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Recompute a release manifest after derived quality tables are added."""
        release_dir = self.versions_dir / self._directory_name(version)
        db_path = release_dir / "worldreasoner.db"
        manifest_path = release_dir / "manifest.json"
        previous: Dict[str, Any] = {}
        if manifest_path.exists():
            previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest = self._build_manifest(
            db_path=db_path,
            version=version,
            parent_version=previous.get("parent_version"),
            operations=operations or previous.get("operations", []),
            source_db=Path(previous.get("source_database", db_path)),
        )
        manifest["llm_passes"] = (
            llm_passes
            if llm_passes is not None
            else previous.get("llm_passes", [])
        )
        manifest["annotation_version"] = previous.get("annotation_version")
        manifest["metric_eligibility_policy"] = previous.get(
            "metric_eligibility_policy"
        )
        manifest["created_at"] = previous.get(
            "created_at", manifest["created_at"]
        )
        manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return manifest

    @staticmethod
    def _sqlite_backup(source_db: Path, target_db: Path) -> None:
        if target_db.exists():
            target_db.unlink()
        with sqlite3.connect(source_db) as source:
            with sqlite3.connect(target_db) as target:
                source.backup(target)

    def _build_manifest(
        self,
        db_path: Path,
        version: str,
        parent_version: Optional[str],
        operations: List[str],
        source_db: Path,
    ) -> Dict[str, Any]:
        counts = self._table_counts(db_path)
        question_ids = self._question_ids(db_path)
        return {
            "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
            "dataset_version": version,
            "parent_version": parent_version,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_database": self._portable_path(source_db),
            "database_file": "worldreasoner.db",
            "database_sha256": self._file_hash(db_path),
            "question_id_sha256": self._text_hash("\n".join(question_ids)),
            "counts": counts,
            "operations": operations,
            "code_revision": self._git_revision(),
            "code_revision_kind": "git_head_base",
            "code_dirty": self._git_dirty(),
            "llm_passes": [],
            "annotation_version": None,
            "metric_eligibility_policy": None,
        }

    @staticmethod
    def _table_counts(db_path: Path) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        with sqlite3.connect(db_path) as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
            for (table,) in tables:
                quoted = table.replace('"', '""')
                counts[table] = conn.execute(
                    f'SELECT COUNT(*) FROM "{quoted}"'
                ).fetchone()[0]
        return counts

    @staticmethod
    def _question_ids(db_path: Path) -> List[str]:
        with sqlite3.connect(db_path) as conn:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='questions'"
            ).fetchone()
            if not exists:
                return []
            rows = conn.execute("SELECT id FROM questions ORDER BY id")
            return [row[0] for row in rows]

    @staticmethod
    def _file_hash(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _text_hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _git_revision() -> Optional[str]:
        try:
            return subprocess.run(
                ["git", "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            return None

    @staticmethod
    def _git_dirty() -> Optional[bool]:
        try:
            status = subprocess.run(
                ["git", "status", "--porcelain"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            return bool(status)
        except (OSError, subprocess.CalledProcessError):
            return None

    @staticmethod
    def _portable_path(path: Path) -> str:
        resolved = path.resolve()
        try:
            return resolved.relative_to(Path.cwd().resolve()).as_posix()
        except ValueError:
            return str(resolved)

    @staticmethod
    def _directory_name(version: str) -> str:
        if not _VERSION_PATTERN.fullmatch(version):
            raise ValueError(
                "Dataset version must contain only letters, numbers, dots, "
                "underscores, and hyphens"
            )
        return version.lower().replace(".", "_").replace("-", "_")
