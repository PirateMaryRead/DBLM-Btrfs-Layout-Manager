from __future__ import annotations

import logging
import warnings
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import tempfile
from typing import Iterator

from core.system import (
    FilesystemContext,
    CommandError,
    run_command,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class BtrfsSubvolume:
    """Represents a Btrfs subvolume entry."""

    subvol_id: int
    generation: int
    parent_id: int
    top_level_id: int
    path: str

    @property
    def name(self) -> str:
        return Path(self.path).name

    @property
    def is_snapshot_path(self) -> bool:
        return "/.snapshots/" in self.path or self.path.startswith("@snapshots/")


@dataclass(slots=True)
class BtrfsContext:
    """A manageable Btrfs filesystem context."""

    label: str
    mountpoint: str
    device: str
    uuid: str
    current_subvol: str | None = None
    current_subvolid: str | None = None

    @property
    def is_valid(self) -> bool:
        return bool(self.device and self.uuid)

    @property
    def normalized_current_subvol(self) -> str | None:
        if not self.current_subvol:
            return None
        if self.current_subvol.startswith("/"):
            return self.current_subvol
        return f"/{self.current_subvol}"


def context_from_filesystem(fs: FilesystemContext, *, label: str) -> BtrfsContext:
    """Create a BtrfsContext from a FilesystemContext."""
    if not fs.is_btrfs:
        raise ValueError(f"{fs.mountpoint} is not a Btrfs filesystem.")

    device = _extract_device_from_source(fs.source)
    return BtrfsContext(
        label=label,
        mountpoint=fs.mountpoint,
        device=device,
        uuid=fs.uuid,
        current_subvol=fs.subvol,
        current_subvolid=fs.subvolid,
    )


def build_contexts(
    *,
    root_fs: FilesystemContext,
    home_fs: FilesystemContext | None = None,
) -> dict[str, BtrfsContext]:
    """
    Build the manageable Btrfs contexts.

    Returns:
        {
            "system": BtrfsContext(...),
            "home": BtrfsContext(...),   # only when /home is separate Btrfs
        }
    """
    contexts: dict[str, BtrfsContext] = {
        "system": context_from_filesystem(root_fs, label="system"),
    }

    if home_fs and home_fs.is_separate_btrfs:
        contexts["home"] = context_from_filesystem(home_fs, label="home")

    return contexts


def is_btrfs_path(path: str | Path) -> bool:
    """Return True if a path is itself a Btrfs subvolume."""
    result = run_command(["btrfs", "subvolume", "show", str(path)])
    return result.ok


def list_subvolumes(context: BtrfsContext) -> list[BtrfsSubvolume]:
    """List subvolumes from the top-level of a Btrfs filesystem."""
    # FIX: capture stdout inside the context manager so parsing happens
    # on data that was fully collected while the mount was still active.
    # Accessing result.stdout outside the `with` block works today because
    # the string is already in memory, but moving parsing inside makes the
    # intent clear and prevents fragility on future refactors.
    with mounted_top_level(context) as top:
        result = run_command(["btrfs", "subvolume", "list", "-p", "-t", str(top)], check=True)
        lines = result.stdout.splitlines()

    items: list[BtrfsSubvolume] = []
    for raw_line in lines:
        parsed = _parse_subvolume_list_line(raw_line)
        if parsed is not None:
            items.append(parsed)

    return items


def subvolume_exists(context: BtrfsContext, subvolume_name: str) -> bool:
    """Return True if a subvolume path already exists in the top-level."""
    subvolume_name = _normalize_subvolume_name(subvolume_name)
    with mounted_top_level(context) as top:
        return (top / subvolume_name.lstrip("/")).exists()


def create_subvolume(
    context: BtrfsContext,
    subvolume_name: str,
    *,
    parents: bool = True,
) -> Path:
    """
    Create a subvolume in the filesystem top-level.

    Example:
        create_subvolume(ctx, "@var@lib@flatpak")
    """
    subvolume_name = _normalize_subvolume_name(subvolume_name)

    with mounted_top_level(context) as top:
        subvol_path = top / subvolume_name.lstrip("/")

        if subvol_path.exists():
            if is_btrfs_path(subvol_path):
                return subvol_path
            raise FileExistsError(f"Path already exists and is not a subvolume: {subvol_path}")

        if parents:
            subvol_path.parent.mkdir(parents=True, exist_ok=True)

        run_command(["btrfs", "subvolume", "create", str(subvol_path)], check=True)
        return subvol_path


def delete_subvolume(
    context: BtrfsContext,
    subvolume_name: str,
    *,
    recursive: bool = False,
) -> None:
    """
    Delete a subvolume from the filesystem top-level.

    Set recursive=True to delete nested subvolumes first.
    """
    subvolume_name = _normalize_subvolume_name(subvolume_name)

    with mounted_top_level(context) as top:
        subvol_path = top / subvolume_name.lstrip("/")
        if not subvol_path.exists():
            raise FileNotFoundError(f"Subvolume path does not exist: {subvol_path}")

        if not is_btrfs_path(subvol_path):
            raise RuntimeError(f"Path exists but is not a Btrfs subvolume: {subvol_path}")

        if recursive:
            _delete_nested_subvolumes_first(subvol_path)

        run_command(["btrfs", "subvolume", "delete", str(subvol_path)], check=True)


def resolve_target_context(
    *,
    target_path: str,
    system_context: BtrfsContext,
    home_context: BtrfsContext | None = None,
) -> BtrfsContext:
    """
    Resolve which Btrfs context should manage a target path.

    Rules:
    - /home and paths under /home use the home context when /home is a separate Btrfs filesystem.
    - everything else uses the system context.
    """
    normalized = str(Path(target_path))
    if home_context and (normalized == "/home" or normalized.startswith("/home/")):
        return home_context
    return system_context


def suggest_flat_subvolume_name(target_path: str) -> str:
    """
    Suggest a flat-layout subvolume name from a mountpoint path.

    Examples:
        /root -> @root
        /var/log -> @var@log
        /var/lib/flatpak -> @var@lib@flatpak
        /home -> @home
    """
    normalized = str(Path(target_path))
    if normalized == "/":
        return "@"
    if normalized == "/.snapshots":
        return "@snapshots"

    parts = [part for part in normalized.split("/") if part]
    return "@" + "@".join(parts)


@contextmanager
def mounted_top_level(context: BtrfsContext) -> Iterator[Path]:
    """
    Mount the Btrfs top-level (subvolid=5) temporarily and yield its path.

    The mount is always attempted to be released in the finally block.
    If the unmount fails after a primary exception, the unmount error is
    logged as a warning so the original exception is not suppressed.
    """
    if not context.is_valid:
        raise ValueError(f"Invalid Btrfs context for {context.label}")

    with tempfile.TemporaryDirectory(prefix=f"dblm-{context.label}-") as temp_dir:
        mountpoint = Path(temp_dir)
        result = run_command(
            ["mount", "-o", "subvolid=5", context.device, str(mountpoint)]
        )
        if not result.ok:
            raise CommandError(
                f"Failed to mount top-level for {context.label} ({context.device}).\n"
                f"stderr: {result.stderr}"
            )

        # FIX: track whether the body raised so we can decide whether to
        # re-raise or warn on unmount failure, preserving the original exception.
        primary_exception_raised = False
        try:
            yield mountpoint
        except Exception:
            primary_exception_raised = True
            raise
        finally:
            unmount = run_command(["umount", str(mountpoint)])
            if not unmount.ok:
                msg = (
                    f"Failed to unmount temporary top-level mount {mountpoint}. "
                    f"stderr: {unmount.stderr}"
                )
                if primary_exception_raised:
                    # Do not suppress the original exception — warn instead.
                    warnings.warn(msg, stacklevel=2)
                    logger.warning(msg)
                else:
                    raise CommandError(msg)


def _extract_device_from_source(source: str) -> str:
    """
    Extract the real device path from a findmnt SOURCE field.

    Example:
        /dev/nvme0n1p2[/@] -> /dev/nvme0n1p2
    """
    source = source.strip()
    if "[" in source:
        return source.split("[", 1)[0]
    return source


def _normalize_subvolume_name(subvolume_name: str) -> str:
    subvolume_name = subvolume_name.strip()
    if not subvolume_name:
        raise ValueError("Subvolume name cannot be empty.")
    return subvolume_name


def _parse_subvolume_list_line(line: str) -> BtrfsSubvolume | None:
    """
    Parse a line from:
        btrfs subvolume list -p -t <path>

    Expected format example:
        ID 256 gen 2579 parent 5 top level 5 path @
    """
    line = line.strip()

    # FIX: added explicit parentheses to make operator precedence unambiguous.
    # Without them, Python evaluates as: (not line) or (line.startswith("ID ") and ...)
    # which happens to be correct, but is fragile and misleading to readers.
    if not line or (line.startswith("ID ") and " path " not in line):
        return None

    try:
        before_path, path = line.split(" path ", 1)
        tokens = before_path.split()

        subvol_id = int(tokens[tokens.index("ID") + 1])
        generation = int(tokens[tokens.index("gen") + 1])
        parent_id = int(tokens[tokens.index("parent") + 1])

        if "level" in tokens:
            # Handles "top level" (two-word token sequence)
            top_level_index = tokens.index("level")
            top_level_id = int(tokens[top_level_index + 1])
        else:
            top_level_id = int(tokens[tokens.index("top") + 1])

        return BtrfsSubvolume(
            subvol_id=subvol_id,
            generation=generation,
            parent_id=parent_id,
            top_level_id=top_level_id,
            path=path.strip(),
        )
    except (ValueError, IndexError):
        return None


def _delete_nested_subvolumes_first(path: Path) -> None:
    """
    Delete nested subvolumes before deleting the parent.

    The deepest paths are deleted first.
    """
    result = run_command(["btrfs", "subvolume", "list", "-o", str(path)], check=True)
    nested_paths: list[Path] = []

    for raw_line in result.stdout.splitlines():
        parsed = _parse_subvolume_list_line(raw_line)
        if parsed is None:
            continue
        nested_paths.append(path.parent / parsed.path)

    for nested in sorted(nested_paths, key=lambda item: len(str(item).split("/")), reverse=True):
        if nested.exists():
            run_command(["btrfs", "subvolume", "delete", str(nested)], check=True)
