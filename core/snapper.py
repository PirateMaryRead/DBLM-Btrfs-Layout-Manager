from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from core.system import command_exists, run_command


@dataclass(slots=True)
class SnapperConfig:
    """Represents a Snapper configuration."""

    name: str
    subvolume: str = ""
    fstype: str = ""
    template: str = ""
    raw: str = ""


@dataclass(slots=True)
class SnapperStatus:
    """High-level Snapper status for DBLM."""

    available: bool
    version: str | None = None
    configs: list[SnapperConfig] = field(default_factory=list)
    timeline_timer: str | None = None
    cleanup_timer: str | None = None
    snapshots_path_exists: bool = False
    snapshots_path_is_dir: bool = False

    @property
    def has_root_config(self) -> bool:
        return any(config.name == "root" for config in self.configs)


def snapper_available() -> bool:
    """Return True when Snapper is available in PATH."""
    return command_exists("snapper")


def get_snapper_version() -> str | None:
    """Return the Snapper version string when available."""
    if not snapper_available():
        return None

    result = run_command(["snapper", "--version"], check=False)
    if not result.ok:
        return None

    first_line = result.stdout.splitlines()[0] if result.stdout else ""
    return first_line.strip() or None


def list_configs() -> list[SnapperConfig]:
    """
    Return Snapper configurations.

    This parser is intentionally conservative because output formatting may vary.
    """
    if not snapper_available():
        return []

    result = run_command(["snapper", "list-configs"], check=False)
    if not result.ok or not result.stdout.strip():
        return []

    configs: list[SnapperConfig] = []
    lines = [line.rstrip() for line in result.stdout.splitlines() if line.strip()]

    if not lines:
        return configs

    # Most common output starts with a header row.
    header = lines[0].lower()
    data_lines = lines[1:] if "config" in header else lines

    for line in data_lines:
        parts = line.split()
        if not parts:
            continue

        # Conservative parsing:
        # config | subvolume | fstype | template
        name = parts[0]
        subvolume = parts[1] if len(parts) > 1 else ""
        fstype = parts[2] if len(parts) > 2 else ""
        template = parts[3] if len(parts) > 3 else ""

        configs.append(
            SnapperConfig(
                name=name,
                subvolume=subvolume,
                fstype=fstype,
                template=template,
                raw=line,
            )
        )

    return configs


def get_config(name: str) -> SnapperConfig | None:
    """Return a Snapper config by name."""
    for config in list_configs():
        if config.name == name:
            return config
    return None


def create_root_config(
    *,
    subvolume: str = "/",
    fstype: str = "btrfs",
    template: str = "default",
) -> bool:
    """
    Create the root Snapper configuration.

    Notes:
    - This is intentionally simple for the first iteration.
    - More advanced setup should be layered on top later.
    """
    if not snapper_available():
        raise RuntimeError("snapper is not available.")

    command = [
        "snapper",
        "-c",
        "root",
        "create-config",
        subvolume,
    ]

    result = run_command(command, check=False)
    return result.ok


def delete_config(name: str) -> bool:
    """Delete a Snapper configuration."""
    if not snapper_available():
        raise RuntimeError("snapper is not available.")

    result = run_command(["snapper", "-c", name, "delete-config"], check=False)
    return result.ok


def systemd_unit_state(unit_name: str) -> str | None:
    """Return a systemd unit state string when possible."""
    if not command_exists("systemctl"):
        return "systemctl unavailable"

    enabled = run_command(["systemctl", "is-enabled", unit_name], check=False)
    if enabled.ok and enabled.stdout:
        return enabled.stdout.strip()

    active = run_command(["systemctl", "is-active", unit_name], check=False)
    if active.ok and active.stdout:
        return active.stdout.strip()

    if enabled.stderr:
        return enabled.stderr.strip()
    return "not found"


def enable_timer(unit_name: str) -> bool:
    """Enable and start a systemd timer."""
    if not command_exists("systemctl"):
        raise RuntimeError("systemctl is not available.")

    result = run_command(["systemctl", "enable", "--now", unit_name], check=False)
    return result.ok


def disable_timer(unit_name: str) -> bool:
    """Disable and stop a systemd timer."""
    if not command_exists("systemctl"):
        raise RuntimeError("systemctl is not available.")

    result = run_command(["systemctl", "disable", "--now", unit_name], check=False)
    return result.ok


def enable_timeline_timer() -> bool:
    """Enable snapper-timeline.timer."""
    return enable_timer("snapper-timeline.timer")


def enable_cleanup_timer() -> bool:
    """Enable snapper-cleanup.timer."""
    return enable_timer("snapper-cleanup.timer")


def disable_timeline_timer() -> bool:
    """Disable snapper-timeline.timer."""
    return disable_timer("snapper-timeline.timer")


def disable_cleanup_timer() -> bool:
    """Disable snapper-cleanup.timer."""
    return disable_timer("snapper-cleanup.timer")


def snapshots_path_status(path: str | Path = "/.snapshots") -> tuple[bool, bool]:
    """Return whether /.snapshots exists and whether it is a directory."""
    snapshots = Path(path)
    return snapshots.exists(), snapshots.is_dir()


def collect_snapper_status() -> SnapperStatus:
    """Collect a high-level Snapper status snapshot."""
    exists, is_dir = snapshots_path_status()

    return SnapperStatus(
        available=snapper_available(),
        version=get_snapper_version(),
        configs=list_configs(),
        timeline_timer=systemd_unit_state("snapper-timeline.timer"),
        cleanup_timer=systemd_unit_state("snapper-cleanup.timer"),
        snapshots_path_exists=exists,
        snapshots_path_is_dir=is_dir,
    )


def validate_snapper_layout(
    *,
    root_is_btrfs: bool,
    snapshots_path: str | Path = "/.snapshots",
) -> list[str]:
    """Return layout warnings relevant to Snapper."""
    warnings: list[str] = []
    exists, is_dir = snapshots_path_status(snapshots_path)

    if not root_is_btrfs:
        warnings.append("Root filesystem is not Btrfs.")
    if not snapper_available():
        warnings.append("Snapper is not installed or not available in PATH.")
    if not exists:
        warnings.append("/.snapshots does not exist.")
    elif not is_dir:
        warnings.append("/.snapshots exists but is not a directory.")

    status = collect_snapper_status()
    if status.available and not status.has_root_config:
        warnings.append("Snapper is available but no root configuration was detected.")

    return warnings
