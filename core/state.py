from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
from typing import Any, Iterator, Literal


logger = logging.getLogger(__name__)

APP_DIR_NAME = "dblm"
DEFAULT_STATE_FILE = Path("data/state.json")
DEFAULT_LOG_DIR = Path("data/logs")

# FIX: typed literals for status fields replace bare strings,
# giving static type checkers (mypy/pyright) the ability to catch
# typos and invalid transitions at analysis time rather than at runtime.
ActionStatus = Literal["pending", "success", "skipped", "failed"]
RunStatus = Literal["planned", "running", "success", "failed", "reverted"]


def utc_now_iso() -> str:
    """Return the current UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(slots=True)
class BackupRecord:
    """Represents a backup created by DBLM."""

    backup_id: str
    original_path: str
    backup_path: str
    created_at: str
    kind: str = "directory"
    source_run_id: str | None = None
    notes: str = ""
    restorable: bool = True
    deleted: bool = False
    restored_at: str | None = None
    deleted_at: str | None = None

    def exists_on_disk(self) -> bool:
        return Path(self.backup_path).exists()


@dataclass(slots=True)
class FstabChange:
    """Represents a single fstab mutation recorded by DBLM."""

    mountpoint: str
    action: str
    new_line: str = ""
    original_line: str = ""
    commented_line: str = ""


@dataclass(slots=True)
class ActionRecord:
    """Represents a subvolume-related action from a single run."""

    target: str
    subvolume: str = ""
    filesystem_scope: str = "system"
    created: bool = False
    migrated: bool = False
    restored: bool = False
    reverted: bool = False
    backup_id: str | None = None
    fstab_changes: list[FstabChange] = field(default_factory=list)
    # FIX: was `str`, now typed as ActionStatus for static analysis safety.
    status: ActionStatus = "pending"
    message: str = ""


@dataclass(slots=True)
class RunRecord:
    """Represents one DBLM execution plan/apply cycle."""

    run_id: str
    created_at: str
    # FIX: was `str`, now typed as RunStatus for static analysis safety.
    status: RunStatus = "planned"
    actions: list[ActionRecord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass(slots=True)
class AppState:
    """Persistent DBLM state stored in JSON."""

    version: int = 1
    app_name: str = "DBLM"
    backups: list[BackupRecord] = field(default_factory=list)
    runs: list[RunRecord] = field(default_factory=list)

    def get_backup(self, backup_id: str) -> BackupRecord | None:
        for backup in self.backups:
            if backup.backup_id == backup_id:
                return backup
        return None

    def get_run(self, run_id: str) -> RunRecord | None:
        for run in self.runs:
            if run.run_id == run_id:
                return run
        return None


class StateManager:
    """Read, write, and manipulate persistent DBLM state."""

    def __init__(self, state_file: str | Path = DEFAULT_STATE_FILE) -> None:
        self.state_file = Path(state_file)
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        # FIX: tracks whether we're inside a batch() context to suppress
        # intermediate save() calls and flush only once at the end.
        self._batch_depth: int = 0
        self.state = self._load()

    # ------------------------------------------------------------------ #
    # Batch context manager                                                #
    # ------------------------------------------------------------------ #

    @contextmanager
    def batch(self) -> Iterator[None]:
        """
        Defer all save() calls until the outermost batch block exits.

        Use this when multiple mutations must be applied together to avoid
        rewriting the state file on every individual operation:

            with state_manager.batch():
                state_manager.add_action(run_id, action1)
                state_manager.add_warning_to_run(run_id, warning)
                state_manager.update_run_status(run_id, "success")
            # state file is written exactly once here

        Batches are re-entrant: nested batch() calls are safe and the file
        is written only when the outermost block exits.
        """
        self._batch_depth += 1
        try:
            yield
        finally:
            self._batch_depth -= 1
            if self._batch_depth == 0:
                self.save()

    # ------------------------------------------------------------------ #
    # Persistence                                                          #
    # ------------------------------------------------------------------ #

    def _load(self) -> AppState:
        if not self.state_file.exists():
            return AppState()

        with self.state_file.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)

        backups = [
            BackupRecord(**item)
            for item in raw.get("backups", [])
        ]
        runs: list[RunRecord] = []
        for raw_run in raw.get("runs", []):
            actions = []
            for raw_action in raw_run.get("actions", []):
                fstab_changes = [
                    FstabChange(**change)
                    for change in raw_action.get("fstab_changes", [])
                ]
                action_data = dict(raw_action)
                action_data["fstab_changes"] = fstab_changes
                actions.append(ActionRecord(**action_data))

            run_data = dict(raw_run)
            run_data["actions"] = actions
            runs.append(RunRecord(**run_data))

        return AppState(
            version=raw.get("version", 1),
            app_name=raw.get("app_name", "DBLM"),
            backups=backups,
            runs=runs,
        )

    def save(self) -> None:
        """
        Persist the current state to disk.

        No-op when called inside a batch() block — the flush is deferred
        until the outermost batch context exits.
        """
        # FIX: skip intermediate writes when inside a batch() context.
        if self._batch_depth > 0:
            return
        payload = asdict(self.state)
        with self.state_file.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=False)
        logger.debug("State saved to %s", self.state_file)

    # ------------------------------------------------------------------ #
    # Run management                                                       #
    # ------------------------------------------------------------------ #

    def new_run(self, notes: str = "") -> RunRecord:
        run = RunRecord(
            run_id=f"run-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
            created_at=utc_now_iso(),
            notes=notes,
        )
        self.state.runs.append(run)
        self.save()
        return run

    def add_run(self, run: RunRecord) -> None:
        self.state.runs.append(run)
        self.save()

    def update_run_status(
        self,
        run_id: str,
        status: RunStatus,
        *,
        notes: str | None = None,
    ) -> None:
        run = self.require_run(run_id)
        run.status = status
        if notes is not None:
            run.notes = notes
        self.save()

    def add_warning_to_run(self, run_id: str, warning: str) -> None:
        run = self.require_run(run_id)
        run.warnings.append(warning)
        self.save()

    def add_action(self, run_id: str, action: ActionRecord) -> None:
        run = self.require_run(run_id)
        run.actions.append(action)
        self.save()

    def find_action(self, run_id: str, target: str) -> ActionRecord | None:
        run = self.require_run(run_id)
        for action in run.actions:
            if action.target == target:
                return action
        return None

    def remove_run(self, run_id: str) -> None:
        self.state.runs = [run for run in self.state.runs if run.run_id != run_id]
        self.save()

    def get_latest_run(self) -> RunRecord | None:
        if not self.state.runs:
            return None
        return self.state.runs[-1]

    def require_run(self, run_id: str) -> RunRecord:
        run = self.state.get_run(run_id)
        if run is None:
            raise KeyError(f"Unknown run id: {run_id}")
        return run

    # ------------------------------------------------------------------ #
    # Backup management                                                    #
    # ------------------------------------------------------------------ #

    def register_backup(
        self,
        *,
        original_path: str,
        backup_path: str,
        kind: str = "directory",
        source_run_id: str | None = None,
        notes: str = "",
    ) -> BackupRecord:
        backup = BackupRecord(
            backup_id=f"backup-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
            original_path=original_path,
            backup_path=backup_path,
            created_at=utc_now_iso(),
            kind=kind,
            source_run_id=source_run_id,
            notes=notes,
        )
        self.state.backups.append(backup)
        self.save()
        return backup

    def list_backups(self, *, include_deleted: bool = False) -> list[BackupRecord]:
        if include_deleted:
            return list(self.state.backups)
        return [item for item in self.state.backups if not item.deleted]

    def list_restorable_backups(self) -> list[BackupRecord]:
        return [
            item
            for item in self.state.backups
            if not item.deleted and item.restorable and item.exists_on_disk()
        ]

    def require_backup(self, backup_id: str) -> BackupRecord:
        backup = self.state.get_backup(backup_id)
        if backup is None:
            raise KeyError(f"Unknown backup id: {backup_id}")
        return backup

    def mark_backup_restored(self, backup_id: str) -> None:
        backup = self.require_backup(backup_id)
        backup.restored_at = utc_now_iso()
        self.save()

    def mark_backup_deleted(self, backup_id: str) -> None:
        backup = self.require_backup(backup_id)
        backup.deleted = True
        backup.deleted_at = utc_now_iso()
        self.save()

    def restore_backup(
        self,
        backup_id: str,
        *,
        overwrite: bool = False,
        create_parent: bool = True,
    ) -> Path:
        """
        Restore a recorded backup to its original path.

        Behavior:
        - If original path does not exist, restore directly.
        - If original path exists and overwrite is False, raise FileExistsError.
        - If original path exists and overwrite is True, remove it first.
        """
        backup = self.require_backup(backup_id)
        backup_path = Path(backup.backup_path)
        original_path = Path(backup.original_path)

        if backup.deleted:
            raise RuntimeError(f"Backup {backup_id} is already marked as deleted.")
        if not backup.restorable:
            raise RuntimeError(f"Backup {backup_id} is not marked as restorable.")
        if not backup_path.exists():
            raise FileNotFoundError(f"Backup path does not exist: {backup_path}")

        if original_path.exists():
            if not overwrite:
                raise FileExistsError(
                    f"Original path already exists and overwrite=False: {original_path}"
                )
            self._remove_path(original_path)

        if create_parent:
            original_path.parent.mkdir(parents=True, exist_ok=True)

        self._copy_path(backup_path, original_path)
        backup.restored_at = utc_now_iso()
        self.save()
        return original_path

    def delete_backup(self, backup_id: str, *, missing_ok: bool = True) -> Path:
        """
        Delete a backup from disk and mark it as deleted in the state file.
        """
        backup = self.require_backup(backup_id)
        backup_path = Path(backup.backup_path)

        if backup.deleted:
            return backup_path

        if backup_path.exists():
            self._remove_path(backup_path)
        elif not missing_ok:
            raise FileNotFoundError(f"Backup path does not exist: {backup_path}")

        backup.deleted = True
        backup.deleted_at = utc_now_iso()
        self.save()
        return backup_path

    def delete_backups(self, backup_ids: list[str], *, missing_ok: bool = True) -> list[Path]:
        """
        Delete multiple backups in a single batch, writing state only once.
        """
        deleted_paths: list[Path] = []
        # FIX: wrap in batch() so delete_backup()'s individual save() calls
        # are suppressed and the file is written only once at the end.
        with self.batch():
            for backup_id in backup_ids:
                deleted_paths.append(self.delete_backup(backup_id, missing_ok=missing_ok))
        return deleted_paths

    # ------------------------------------------------------------------ #
    # Summary                                                              #
    # ------------------------------------------------------------------ #

    def summarize(self) -> dict[str, Any]:
        available_backups = [b for b in self.state.backups if not b.deleted]
        restorable = [b for b in available_backups if b.restorable and b.exists_on_disk()]
        deleted = [b for b in self.state.backups if b.deleted]

        return {
            "runs_total": len(self.state.runs),
            "backups_total": len(self.state.backups),
            "backups_available": len(available_backups),
            "backups_restorable": len(restorable),
            "backups_deleted": len(deleted),
            "latest_run_id": self.state.runs[-1].run_id if self.state.runs else None,
        }

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _copy_path(source: Path, target: Path) -> None:
        if source.is_dir():
            shutil.copytree(source, target, symlinks=True)
        else:
            shutil.copy2(source, target)

    @staticmethod
    def _remove_path(path: Path) -> None:
        if path.is_symlink() or path.is_file():
            path.unlink()
            return
        if path.is_dir():
            shutil.rmtree(path)
            return
        raise FileNotFoundError(f"Cannot remove missing path: {path}")
