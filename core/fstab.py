from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import shutil

from core.logging import get_logger


DEFAULT_FSTAB_PATH = Path("/etc/fstab")
MANAGED_COMMENT_PREFIX = "# DBLM:"
MIGRATED_COMMENT_PREFIX = "# DBLM-MIGRATED:"

OperationLogger = Callable[[str, str, str], None]


def _noop_operation_logger(message: str, level: str = "info", source: str = "fstab") -> None:
    """Default operation logger used when no callback is provided."""
    return None


LOGGER = get_logger("fstab")


@dataclass(slots=True)
class FstabEntry:
    """Represents a parsed fstab entry or preserved raw line."""

    raw: str
    is_comment: bool
    is_blank: bool
    fs_spec: str = ""
    mountpoint: str = ""
    fstype: str = ""
    options: str = ""
    dump: str = ""
    passno: str = ""
    parse_error: str | None = None

    @property
    def is_active(self) -> bool:
        return (
            not self.is_comment
            and not self.is_blank
            and bool(self.mountpoint)
            and self.parse_error is None
        )

    @property
    def is_invalid(self) -> bool:
        return self.parse_error is not None

    @property
    def managed_by_dblm(self) -> bool:
        return self.raw.startswith(MANAGED_COMMENT_PREFIX) or "dblm-managed" in self.options


@dataclass(slots=True)
class FstabConflict:
    """Represents a conflicting mountpoint definition."""

    mountpoint: str
    indexes: list[int]
    lines: list[str]


@dataclass(slots=True)
class FstabMutationResult:
    """Describes changes made to the fstab buffer."""

    backup_path: str | None
    added_lines: list[str]
    commented_lines: list[str]
    removed_lines: list[str]


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def parse_fstab_line(line: str) -> FstabEntry:
    """Parse a single fstab line while preserving raw content."""
    raw = line.rstrip("\n")
    stripped = raw.strip()

    if not stripped:
        return FstabEntry(raw=raw, is_comment=False, is_blank=True)

    if stripped.startswith("#"):
        return FstabEntry(raw=raw, is_comment=True, is_blank=False)

    parts = stripped.split()
    if len(parts) < 6:
        return FstabEntry(
            raw=raw,
            is_comment=False,
            is_blank=False,
            parse_error="Invalid fstab line: expected at least 6 fields.",
        )

    return FstabEntry(
        raw=raw,
        is_comment=False,
        is_blank=False,
        fs_spec=parts[0],
        mountpoint=parts[1],
        fstype=parts[2],
        options=parts[3],
        dump=parts[4],
        passno=parts[5],
    )


def read_fstab(path: str | Path = DEFAULT_FSTAB_PATH) -> list[FstabEntry]:
    """Read and parse /etc/fstab."""
    fstab_path = Path(path)
    if not fstab_path.exists():
        raise FileNotFoundError(f"fstab not found: {fstab_path}")

    LOGGER.info("Reading fstab from %s", fstab_path)
    with fstab_path.open("r", encoding="utf-8") as handle:
        return [parse_fstab_line(line) for line in handle.readlines()]


def render_fstab(entries: list[FstabEntry]) -> str:
    """Render parsed entries back to a file string."""
    return "\n".join(entry.raw for entry in entries) + "\n"


def write_fstab(
    entries: list[FstabEntry],
    *,
    path: str | Path = DEFAULT_FSTAB_PATH,
    create_backup: bool = True,
    operation_log: OperationLogger | None = None,
) -> str | None:
    """Write the full fstab and optionally create a timestamped backup first."""
    log = operation_log or _noop_operation_logger
    fstab_path = Path(path)
    backup_path: str | None = None

    LOGGER.info("Writing fstab to %s (create_backup=%s)", fstab_path, create_backup)
    log(f"Writing fstab to {fstab_path}", "info", "fstab")

    if create_backup and fstab_path.exists():
        backup = backup_fstab(fstab_path, operation_log=operation_log)
        backup_path = str(backup)

    with fstab_path.open("w", encoding="utf-8") as handle:
        handle.write(render_fstab(entries))

    log("fstab write completed.", "info", "fstab")
    return backup_path


def backup_fstab(
    path: str | Path = DEFAULT_FSTAB_PATH,
    *,
    operation_log: OperationLogger | None = None,
) -> Path:
    """Create a timestamped backup of fstab."""
    log = operation_log or _noop_operation_logger
    fstab_path = Path(path)
    backup_path = fstab_path.with_name(f"{fstab_path.name}.bak.{utc_stamp()}")
    LOGGER.info("Creating fstab backup: %s -> %s", fstab_path, backup_path)
    log(f"Creating fstab backup at {backup_path}", "info", "fstab")
    shutil.copy2(fstab_path, backup_path)
    return backup_path


def restore_fstab_backup(
    backup_path: str | Path,
    *,
    path: str | Path = DEFAULT_FSTAB_PATH,
    operation_log: OperationLogger | None = None,
) -> Path:
    """Restore a previously created fstab backup."""
    log = operation_log or _noop_operation_logger
    source = Path(backup_path)
    target = Path(path)

    if not source.exists():
        raise FileNotFoundError(f"fstab backup not found: {source}")

    LOGGER.info("Restoring fstab backup: %s -> %s", source, target)
    log(f"Restoring fstab backup from {source}", "warning", "fstab")
    shutil.copy2(source, target)
    log("fstab backup restored.", "info", "fstab")
    return target


def delete_fstab_backup(
    backup_path: str | Path,
    *,
    missing_ok: bool = True,
    operation_log: OperationLogger | None = None,
) -> Path:
    """Delete a previously created fstab backup."""
    log = operation_log or _noop_operation_logger
    backup = Path(backup_path)
    if backup.exists():
        LOGGER.info("Deleting fstab backup: %s", backup)
        backup.unlink()
        log(f"Deleted fstab backup {backup}", "info", "fstab")
    elif not missing_ok:
        raise FileNotFoundError(f"fstab backup not found: {backup}")
    return backup


def detect_conflicts(entries: list[FstabEntry]) -> list[FstabConflict]:
    """Detect duplicate active mountpoints."""
    mount_map: dict[str, list[tuple[int, FstabEntry]]] = {}

    for index, entry in enumerate(entries):
        if not entry.is_active:
            continue
        mount_map.setdefault(entry.mountpoint, []).append((index, entry))

    conflicts: list[FstabConflict] = []
    for mountpoint, items in mount_map.items():
        if len(items) > 1:
            conflicts.append(
                FstabConflict(
                    mountpoint=mountpoint,
                    indexes=[index for index, _ in items],
                    lines=[entry.raw for _, entry in items],
                )
            )

    if conflicts:
        LOGGER.warning("Detected %s fstab conflict(s).", len(conflicts))
    return conflicts


def find_invalid_entries(entries: list[FstabEntry]) -> list[tuple[int, FstabEntry]]:
    """Return invalid fstab entries with their indexes."""
    return [
        (index, entry)
        for index, entry in enumerate(entries)
        if entry.is_invalid
    ]


def find_entries_for_mountpoint(entries: list[FstabEntry], mountpoint: str) -> list[int]:
    """Return indexes of active entries for a given mountpoint."""
    return [
        index
        for index, entry in enumerate(entries)
        if entry.is_active and entry.mountpoint == mountpoint
    ]


def build_btrfs_entry(
    *,
    uuid: str,
    mountpoint: str,
    subvolume: str,
    options: str = "defaults,noatime,space_cache=v2,compress=zstd,dblm-managed",
    dump: str = "0",
    passno: str = "0",
) -> FstabEntry:
    """Build a Btrfs mount entry in DBLM's standard format."""
    raw = f"UUID={uuid} {mountpoint} btrfs subvol=/{subvolume},{options} {dump} {passno}"
    return FstabEntry(
        raw=raw,
        is_comment=False,
        is_blank=False,
        fs_spec=f"UUID={uuid}",
        mountpoint=mountpoint,
        fstype="btrfs",
        options=f"subvol=/{subvolume},{options}",
        dump=dump,
        passno=passno,
    )


def comment_out_mountpoint(
    entries: list[FstabEntry],
    mountpoint: str,
    *,
    only_active: bool = True,
    operation_log: OperationLogger | None = None,
) -> list[str]:
    """
    Comment out all matching entries for a mountpoint.

    Returns the list of original lines that were commented.
    """
    log = operation_log or _noop_operation_logger
    commented: list[str] = []

    for index, entry in enumerate(entries):
        if only_active and not entry.is_active:
            continue
        if entry.mountpoint != mountpoint:
            continue

        original = entry.raw
        commented.append(original)
        entries[index] = FstabEntry(
            raw=f"{MIGRATED_COMMENT_PREFIX} {original}",
            is_comment=True,
            is_blank=False,
        )

    if commented:
        LOGGER.info("Commented out %s fstab line(s) for mountpoint %s", len(commented), mountpoint)
        log(f"Commented existing fstab entries for {mountpoint}", "warning", "fstab")

    return commented


def remove_mountpoint(
    entries: list[FstabEntry],
    mountpoint: str,
    *,
    operation_log: OperationLogger | None = None,
) -> list[str]:
    """
    Remove all active entries for a mountpoint.

    Returns the removed raw lines.
    """
    log = operation_log or _noop_operation_logger
    removed: list[str] = []
    kept: list[FstabEntry] = []

    for entry in entries:
        if entry.is_active and entry.mountpoint == mountpoint:
            removed.append(entry.raw)
            continue
        kept.append(entry)

    entries[:] = kept

    if removed:
        LOGGER.info("Removed %s fstab line(s) for mountpoint %s", len(removed), mountpoint)
        log(f"Removed active fstab entries for {mountpoint}", "warning", "fstab")

    return removed


def append_entry(
    entries: list[FstabEntry],
    entry: FstabEntry,
    *,
    operation_log: OperationLogger | None = None,
) -> None:
    """Append an entry to the in-memory fstab list."""
    log = operation_log or _noop_operation_logger
    entries.append(entry)
    LOGGER.info("Appended fstab entry for mountpoint %s", entry.mountpoint or "<comment>")
    if entry.mountpoint:
        log(f"Appended new fstab entry for {entry.mountpoint}", "info", "fstab")


def ensure_mount_entry(
    entries: list[FstabEntry],
    *,
    uuid: str,
    mountpoint: str,
    subvolume: str,
    options: str = "defaults,noatime,space_cache=v2,compress=zstd,dblm-managed",
    comment_existing: bool = True,
    operation_log: OperationLogger | None = None,
) -> FstabMutationResult:
    """
    Ensure a DBLM-managed Btrfs mount entry exists for a mountpoint.

    If active entries already exist for the same mountpoint, they may be commented
    out first.
    """
    log = operation_log or _noop_operation_logger
    added_lines: list[str] = []
    commented_lines: list[str] = []
    removed_lines: list[str] = []

    LOGGER.info(
        "Ensuring mount entry for mountpoint=%s subvolume=%s comment_existing=%s",
        mountpoint,
        subvolume,
        comment_existing,
    )
    log(f"Ensuring fstab entry for {mountpoint} -> /{subvolume}", "info", "fstab")

    current_indexes = find_entries_for_mountpoint(entries, mountpoint)
    desired_entry = build_btrfs_entry(
        uuid=uuid,
        mountpoint=mountpoint,
        subvolume=subvolume,
        options=options,
    )

    for index in current_indexes:
        current = entries[index]
        if current.raw == desired_entry.raw:
            log(f"Desired fstab entry for {mountpoint} already exists.", "info", "fstab")
            return FstabMutationResult(
                backup_path=None,
                added_lines=[],
                commented_lines=[],
                removed_lines=[],
            )

    if current_indexes and comment_existing:
        commented_lines = comment_out_mountpoint(
            entries,
            mountpoint,
            operation_log=operation_log,
        )
    elif current_indexes:
        removed_lines = remove_mountpoint(
            entries,
            mountpoint,
            operation_log=operation_log,
        )

    managed_comment = FstabEntry(
        raw=f"{MANAGED_COMMENT_PREFIX} mountpoint={mountpoint} subvolume={subvolume}",
        is_comment=True,
        is_blank=False,
    )
    append_entry(entries, managed_comment, operation_log=operation_log)
    append_entry(entries, desired_entry, operation_log=operation_log)
    added_lines.extend([managed_comment.raw, desired_entry.raw])

    log(f"Prepared managed fstab entry for {mountpoint}.", "info", "fstab")
    return FstabMutationResult(
        backup_path=None,
        added_lines=added_lines,
        commented_lines=commented_lines,
        removed_lines=removed_lines,
    )


def restore_commented_mountpoint(
    entries: list[FstabEntry],
    mountpoint: str,
    *,
    operation_log: OperationLogger | None = None,
) -> int:
    """
    Restore lines previously commented by DBLM for a mountpoint.

    Returns the number of restored lines.
    """
    log = operation_log or _noop_operation_logger
    restored = 0

    for index, entry in enumerate(entries):
        if not entry.is_comment:
            continue
        if not entry.raw.startswith(MIGRATED_COMMENT_PREFIX):
            continue

        original = entry.raw.removeprefix(f"{MIGRATED_COMMENT_PREFIX} ").strip()
        parsed = parse_fstab_line(original)
        if parsed.mountpoint == mountpoint:
            entries[index] = parsed
            restored += 1

    if restored:
        LOGGER.info("Restored %s commented fstab line(s) for mountpoint %s", restored, mountpoint)
        log(f"Restored {restored} commented fstab entry/entries for {mountpoint}", "info", "fstab")

    return restored


def remove_dblm_managed_entry(
    entries: list[FstabEntry],
    mountpoint: str,
    *,
    operation_log: OperationLogger | None = None,
) -> list[str]:
    """
    Remove DBLM-managed comment markers and active mount entries for a mountpoint.
    """
    log = operation_log or _noop_operation_logger
    removed: list[str] = []
    kept: list[FstabEntry] = []

    for entry in entries:
        is_marker = entry.is_comment and entry.raw.startswith(f"{MANAGED_COMMENT_PREFIX} ")
        if is_marker and f"mountpoint={mountpoint}" in entry.raw:
            removed.append(entry.raw)
            continue

        if entry.is_active and entry.mountpoint == mountpoint and "dblm-managed" in entry.options:
            removed.append(entry.raw)
            continue

        kept.append(entry)

    entries[:] = kept

    if removed:
        LOGGER.info("Removed %s DBLM-managed fstab line(s) for mountpoint %s", len(removed), mountpoint)
        log(f"Removed DBLM-managed fstab entries for {mountpoint}", "warning", "fstab")

    return removed


def revert_mountpoint_change(
    entries: list[FstabEntry],
    mountpoint: str,
    *,
    operation_log: OperationLogger | None = None,
) -> FstabMutationResult:
    """
    Revert a mountpoint change by removing DBLM-managed lines and restoring old ones.
    """
    log = operation_log or _noop_operation_logger
    LOGGER.info("Reverting fstab mountpoint change for %s", mountpoint)
    log(f"Reverting fstab changes for {mountpoint}", "warning", "fstab")

    removed_lines = remove_dblm_managed_entry(
        entries,
        mountpoint,
        operation_log=operation_log,
    )
    restored_count = restore_commented_mountpoint(
        entries,
        mountpoint,
        operation_log=operation_log,
    )

    commented_lines: list[str] = []
    if restored_count:
        commented_lines.append(f"restored={restored_count}")

    log(f"fstab revert completed for {mountpoint}", "info", "fstab")
    return FstabMutationResult(
        backup_path=None,
        added_lines=[],
        commented_lines=commented_lines,
        removed_lines=removed_lines,
    )
