from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from core.logging import get_logger
from core.system import command_exists, run_command


OperationLogger = Callable[[str, str, str], None]


def _noop_operation_logger(message: str, level: str = "info", source: str = "snapper") -> None:
    """Default operation logger used when no callback is provided."""
    return None


LOGGER = get_logger("snapper")


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
    available = command_exists("snapper")
    LOGGER.info("Snapper availability check: %s", available)
    return available


def get_snapper_version() -> str | None:
    """Return the Snapper version string when available."""
    if not snapper_available():
        return None

    result = run_command(["snapper", "--version"], check=False)
    if not result.ok:
        LOGGER.warning("Failed to query Snapper version.")
        return None

    first_line = result.stdout.splitlines()[0] if result.stdout else ""
    version = first_line.strip() or None
    LOGGER.info("Detected Snapper version: %s", version)
    return version


def list_configs() -> list[SnapperConfig]:
    """
    Return Snapper configurations.

    This parser is intentionally conservative because output formatting may vary.
    """
    if not snapper_available():
        return []

    result = run_command(["snapper", "list-configs"], check=False)
    if not result.ok or not result.stdout.strip():
        LOGGER.info("No Snapper configurations detected.")
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

    LOGGER.info("Detected %s Snapper configuration(s).", len(configs))
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
    operation_log: OperationLogger | None = None,
) -> bool:
    """
    Create the root Snapper configuration.

    Notes:
    - This is intentionally simple for the first iteration.
    - More advanced setup should be layered on top later.
    """
    log = operation_log or _noop_operation_logger

    if not snapper_available():
        raise RuntimeError("snapper is not available.")

    command = [
        "snapper",
        "-c",
        "root",
        "create-config",
        subvolume,
    ]

    LOGGER.info(
        "Creating Snapper root config (subvolume=%s, fstype=%s, template=%s).",
        subvolume,
        fstype,
        template,
    )
    log(f"Creating Snapper root configuration for {subvolume}", "info", "snapper")
    result = run_command(command, check=False)
    if result.ok:
        log("Snapper root configuration created successfully.", "info", "snapper")
    else:
        log("Failed to create Snapper root configuration.", "error", "snapper")
    return result.ok


def delete_config(
    name: str,
    *,
    operation_log: OperationLogger | None = None,
) -> bool:
    """Delete a Snapper configuration."""
    log = operation_log or _noop_operation_logger

    if not snapper_available():
        raise RuntimeError("snapper is not available.")

    LOGGER.info("Deleting Snapper configuration: %s", name)
    log(f"Deleting Snapper configuration {name}", "warning", "snapper")
    result = run_command(["snapper", "-c", name, "delete-config"], check=False)
    if result.ok:
        log(f"Deleted Snapper configuration {name}", "info", "snapper")
    else:
        log(f"Failed to delete Snapper configuration {name}", "error", "snapper")
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


def enable_timer(
    unit_name: str,
    *,
    operation_log: OperationLogger | None = None,
) -> bool:
    """Enable and start a systemd timer."""
    log = operation_log or _noop_operation_logger

    if not command_exists("systemctl"):
        raise RuntimeError("systemctl is not available.")

    LOGGER.info("Enabling timer: %s", unit_name)
    log(f"Enabling timer {unit_name}", "info", "systemd")
    result = run_command(["systemctl", "enable", "--now", unit_name], check=False)
    if result.ok:
        log(f"Enabled timer {unit_name}", "info", "systemd")
    else:
        log(f"Failed to enable timer {unit_name}", "error", "systemd")
    return result.ok


def disable_timer(
    unit_name: str,
    *,
    operation_log: OperationLogger | None = None,
) -> bool:
    """Disable and stop a systemd timer."""
    log = operation_log or _noop_operation_logger

    if not command_exists("systemctl"):
        raise RuntimeError("systemctl is not available.")

    LOGGER.info("Disabling timer: %s", unit_name)
    log(f"Disabling timer {unit_name}", "warning", "systemd")
    result = run_command(["systemctl", "disable", "--now", unit_name], check=False)
    if result.ok:
        log(f"Disabled timer {unit_name}", "info", "systemd")
    else:
        log(f"Failed to disable timer {unit_name}", "error", "systemd")
    return result.ok


def enable_timeline_timer(*, operation_log: OperationLogger | None = None) -> bool:
    """Enable snapper-timeline.timer."""
    return enable_timer("snapper-timeline.timer", operation_log=operation_log)


def enable_cleanup_timer(*, operation_log: OperationLogger | None = None) -> bool:
    """Enable snapper-cleanup.timer."""
    return enable_timer("snapper-cleanup.timer", operation_log=operation_log)


def disable_timeline_timer(*, operation_log: OperationLogger | None = None) -> bool:
    """Disable snapper-timeline.timer."""
    return disable_timer("snapper-timeline.timer", operation_log=operation_log)


def disable_cleanup_timer(*, operation_log: OperationLogger | None = None) -> bool:
    """Disable snapper-cleanup.timer."""
    return disable_timer("snapper-cleanup.timer", operation_log=operation_log)


def snapshots_path_status(path: str | Path = "/.snapshots") -> tuple[bool, bool]:
    """Return whether /.snapshots exists and whether it is a directory."""
    snapshots = Path(path)
    exists, is_dir = snapshots.exists(), snapshots.is_dir()
    LOGGER.info("Snapshots path status for %s: exists=%s is_dir=%s", snapshots, exists, is_dir)
    return exists, is_dir


def collect_snapper_status() -> SnapperStatus:
    """Collect a high-level Snapper status snapshot."""
    exists, is_dir = snapshots_path_status()

    status = SnapperStatus(
        available=snapper_available(),
        version=get_snapper_version(),
        configs=list_configs(),
        timeline_timer=systemd_unit_state("snapper-timeline.timer"),
        cleanup_timer=systemd_unit_state("snapper-cleanup.timer"),
        snapshots_path_exists=exists,
        snapshots_path_is_dir=is_dir,
    )
    LOGGER.info(
        "Collected Snapper status (available=%s, configs=%s, root_config=%s).",
        status.available,
        len(status.configs),
        status.has_root_config,
    )
    return status


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

    if warnings:
        LOGGER.warning("Snapper layout validation produced %s warning(s).", len(warnings))
    else:
        LOGGER.info("Snapper layout validation produced no warnings.")
    return warnings
