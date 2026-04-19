from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import shutil
import tempfile
from typing import Iterator

from core.btrfs import (
    BtrfsContext,
    create_subvolume,
    delete_subvolume,
    is_btrfs_path,
)
from core.state import ActionRecord, StateManager
from core.system import CommandError, command_exists, run_command


DEFAULT_BACKUP_SUFFIX = ".dblm-backup"
DEFAULT_BACKUP_ROOT = Path("/var/lib/dblm/backups")


@dataclass(slots=True)
class ServiceStopResult:
    """Tracks which services were stopped or skipped."""

    stopped: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)


@dataclass(slots=True)
class MigrationRequest:
    """Input parameters for a path-to-subvolume migration."""

    target_path: str
    subvolume_name: str
    filesystem_scope: str = "system"
    create_backup: bool = True
    backup_root: str | Path = DEFAULT_BACKUP_ROOT
    stop_related_services: bool = True
    register_state: bool = True


@dataclass(slots=True)
class MigrationResult:
    """Result of a migration operation."""

    target_path: str
    subvolume_name: str
    created_subvolume: bool
    backup_id: str | None = None
    backup_path: str | None = None
    copied: bool = False
    services: ServiceStopResult = field(default_factory=ServiceStopResult)
    status: str = "success"
    message: str = ""


def utc_stamp() -> str:
    """Return a compact UTC timestamp string."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def ensure_directory(path: str | Path) -> Path:
    """Create a directory if needed and return it."""
    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def has_meaningful_contents(path: str | Path) -> bool:
    """Return True when a directory contains at least one entry."""
    directory = Path(path)
    if not directory.exists():
        return False
    return any(directory.iterdir())


def build_backup_path(
    original_path: str | Path,
    *,
    backup_root: str | Path = DEFAULT_BACKUP_ROOT,
    suffix: str = DEFAULT_BACKUP_SUFFIX,
) -> Path:
    """Build a timestamped backup path for a target directory."""
    original = Path(original_path)
    root = Path(backup_root)
    safe_name = original.as_posix().strip("/").replace("/", "__") or "root"
    return root / f"{safe_name}{suffix}.{utc_stamp()}"


def create_directory_backup(
    original_path: str | Path,
    *,
    backup_root: str | Path = DEFAULT_BACKUP_ROOT,
) -> Path:
    """
    Move an existing path out of the way into the DBLM backup area.

    Uses shutil.move instead of Path.rename so it also works when the source and
    backup destination are on different filesystems.
    """
    original = Path(original_path)
    if not original.exists():
        raise FileNotFoundError(f"Cannot back up missing path: {original}")

    ensure_directory(backup_root)
    backup_path = build_backup_path(original, backup_root=backup_root)
    shutil.move(str(original), str(backup_path))
    return backup_path


def copy_tree_with_rsync(source: str | Path, target: str | Path) -> None:
    """Copy a directory tree with rsync while preserving attributes."""
    source_path = Path(source)
    target_path = Path(target)

    ensure_directory(target_path)
    result = run_command(
        [
            "rsync",
            "-aHAX",
            "--numeric-ids",
            f"{source_path}/",
            f"{target_path}/",
        ],
        check=False,
    )
    if not result.ok:
        raise CommandError(
            f"rsync failed while copying {source_path} -> {target_path}\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )


def related_services_for_path(target_path: str | Path) -> list[str]:
    """Return likely services related to a managed path."""
    normalized = str(Path(target_path))

    if normalized.startswith("/var/lib/libvirt"):
        return ["libvirtd.service", "virtqemud.service"]
    if normalized.startswith("/var/lib/containers"):
        return ["podman.service", "podman.socket", "docker.service", "docker.socket"]
    if normalized.startswith("/var/lib/waydroid"):
        return ["waydroid-container.service"]
    return []


def stop_services(service_names: list[str]) -> ServiceStopResult:
    """Stop known services if systemctl is available."""
    result = ServiceStopResult()

    if not service_names:
        return result

    if not command_exists("systemctl"):
        result.skipped.extend(service_names)
        return result

    for service in service_names:
        enabled_check = run_command(["systemctl", "list-unit-files", service], check=False)
        if not enabled_check.ok:
            result.skipped.append(service)
            continue

        active_check = run_command(["systemctl", "is-active", "--quiet", service], check=False)
        if active_check.returncode == 0:
            stop_result = run_command(["systemctl", "stop", service], check=False)
            if stop_result.ok:
                result.stopped.append(service)
            else:
                result.failed.append(service)
        else:
            result.skipped.append(service)

    return result


def warn_if_flatpak_running() -> bool:
    """Return True when flatpak processes appear to be running."""
    if not command_exists("flatpak"):
        return False

    result = run_command(["flatpak", "ps"], check=False)
    return result.ok and bool(result.stdout.strip())


@contextmanager
def mounted_subvolume(
    context: BtrfsContext,
    subvolume_name: str,
) -> Iterator[Path]:
    """
    Mount a specific subvolume temporarily and yield the mountpoint path.

    Preserves the original exception from the managed block if unmount also
    fails during cleanup.
    """
    with tempfile.TemporaryDirectory(prefix=f"dblm-subvol-{context.label}-") as temp_dir:
        mountpoint = Path(temp_dir)
        result = run_command(
            ["mount", "-o", f"subvol=/{subvolume_name}", context.device, str(mountpoint)],
            check=False,
        )
        if not result.ok:
            raise CommandError(
                f"Failed to mount subvolume /{subvolume_name} on {mountpoint}\n"
                f"stderr: {result.stderr}"
            )

        original_error: BaseException | None = None
        try:
            yield mountpoint
        except BaseException as exc:
            original_error = exc
            raise
        finally:
            unmount = run_command(["umount", str(mountpoint)], check=False)
            if not unmount.ok and original_error is None:
                raise CommandError(
                    f"Failed to unmount temporary subvolume mount {mountpoint}\n"
                    f"stderr: {unmount.stderr}"
                )


def mount_subvolume_at_path(
    context: BtrfsContext,
    subvolume_name: str,
    mountpoint: str | Path,
) -> None:
    """Mount a subvolume directly at its final path."""
    target = Path(mountpoint)
    ensure_directory(target)

    result = run_command(
        ["mount", "-o", f"subvol=/{subvolume_name}", context.device, str(target)],
        check=False,
    )
    if not result.ok:
        raise CommandError(
            f"Failed to mount subvolume /{subvolume_name} at {target}\n"
            f"stderr: {result.stderr}"
        )


def unmount_path(path: str | Path) -> None:
    """Unmount a path if it is currently mounted."""
    result = run_command(["umount", str(path)], check=False)
    if not result.ok:
        raise CommandError(f"Failed to unmount {path}\nstderr: {result.stderr}")


def is_exact_mountpoint(path: str | Path) -> bool:
    """Return True only when the path itself is an active mountpoint."""
    target = str(Path(path))
    result = run_command(
        ["findmnt", "-n", "-o", "TARGET", "--target", target],
        check=False,
    )
    return result.ok and result.stdout.strip() == target


def migrate_path_to_subvolume(
    *,
    context: BtrfsContext,
    request: MigrationRequest,
    state_manager: StateManager | None = None,
    run_id: str | None = None,
) -> MigrationResult:
    """
    Create a subvolume, copy current contents into it, and back up the original directory.

    Notes:
    - This function does not edit fstab.
    - It does not permanently mount the new subvolume unless mounted later by another step.
    """
    target = Path(request.target_path)

    if target.exists() and is_btrfs_path(target):
        return MigrationResult(
            target_path=request.target_path,
            subvolume_name=request.subvolume_name,
            created_subvolume=False,
            status="skipped",
            message="Target path is already a Btrfs subvolume.",
        )

    if request.stop_related_services:
        services = stop_services(related_services_for_path(target))
    else:
        services = ServiceStopResult()

    create_subvolume(context, request.subvolume_name)
    created_subvolume = True

    copied = False
    backup_id: str | None = None
    backup_path: str | None = None

    with mounted_subvolume(context, request.subvolume_name) as mounted_target:
        if target.exists() and has_meaningful_contents(target):
            copy_tree_with_rsync(target, mounted_target)
            copied = True

    if target.exists():
        if request.create_backup:
            created_backup = create_directory_backup(
                target,
                backup_root=request.backup_root,
            )
            backup_path = str(created_backup)

            if state_manager is not None:
                backup = state_manager.register_backup(
                    original_path=str(target),
                    backup_path=backup_path,
                    kind="directory",
                    source_run_id=run_id,
                    notes=(
                        f"Backup created before migrating {target} "
                        f"to subvolume {request.subvolume_name}"
                    ),
                )
                backup_id = backup.backup_id
        else:
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()

    ensure_directory(target)

    if state_manager is not None and run_id and request.register_state:
        state_manager.add_action(
            run_id,
            ActionRecord(
                target=request.target_path,
                subvolume=request.subvolume_name,
                filesystem_scope=request.filesystem_scope,
                created=created_subvolume,
                migrated=True,
                backup_id=backup_id,
                status="success",
                message=f"Migrated {request.target_path} to subvolume {request.subvolume_name}",
            ),
        )

    return MigrationResult(
        target_path=request.target_path,
        subvolume_name=request.subvolume_name,
        created_subvolume=created_subvolume,
        backup_id=backup_id,
        backup_path=backup_path,
        copied=copied,
        services=services,
        status="success",
        message="Migration prepared successfully.",
    )


def restore_backup(
    state_manager: StateManager,
    backup_id: str,
    *,
    overwrite: bool = False,
) -> Path:
    """
    Restore a recorded backup to its original path.

    This is a thin wrapper over StateManager.restore_backup so the UI can depend
    on migration helpers instead of manipulating state directly.
    """
    return state_manager.restore_backup(backup_id, overwrite=overwrite)


def delete_backup(
    state_manager: StateManager,
    backup_id: str,
    *,
    missing_ok: bool = True,
) -> Path:
    """
    Delete a recorded backup from disk and mark it as deleted in state.
    """
    return state_manager.delete_backup(backup_id, missing_ok=missing_ok)


def delete_backups(
    state_manager: StateManager,
    backup_ids: list[str],
    *,
    missing_ok: bool = True,
) -> list[Path]:
    """Delete multiple recorded backups."""
    return state_manager.delete_backups(backup_ids, missing_ok=missing_ok)


def rollback_migration(
    *,
    context: BtrfsContext,
    target_path: str,
    subvolume_name: str,
    state_manager: StateManager | None = None,
    backup_id: str | None = None,
    remove_subvolume: bool = True,
    restore_original: bool = True,
    overwrite_restore: bool = True,
    recursive_delete: bool = False,
) -> None:
    """
    Roll back a migration by unmounting the target path, restoring its backup,
    and optionally deleting the created subvolume.
    """
    target = Path(target_path)

    if target.exists() and is_exact_mountpoint(target):
        unmount_path(target)

    if target.exists() and not target.is_symlink():
        if target.is_dir():
            try:
                target.rmdir()
            except OSError:
                # Leave non-empty directories in place unless restore_backup with overwrite handles them.
                pass

    if restore_original and state_manager is not None and backup_id is not None:
        state_manager.restore_backup(backup_id, overwrite=overwrite_restore)

    if remove_subvolume:
        delete_subvolume(context, subvolume_name, recursive=recursive_delete)
