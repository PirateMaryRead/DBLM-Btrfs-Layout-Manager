from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from core.logging import get_logger
from core.system import command_exists, run_command


OperationLogger = Callable[[str, str, str], None]


def _noop_operation_logger(message: str, level: str = "info", source: str = "boot") -> None:
    """Default operation logger used when no callback is provided."""
    return None


LOGGER = get_logger("boot")


@dataclass(slots=True)
class GrubStatus:
    """Represents the current GRUB toolchain status."""

    available: bool
    grub_install: bool = False
    grub_mkconfig: bool = False
    grub_cfg_paths: list[str] = field(default_factory=list)
    grub_btrfsd: bool = False
    grub_btrfs_path_unit: str | None = None
    grub_btrfs_service_unit: str | None = None


@dataclass(slots=True)
class SystemdBootStatus:
    """Represents the current systemd-boot status."""

    available: bool
    installed: bool = False
    version: str | None = None
    efi_mountpoint: str | None = None
    loader_entries_dir: str | None = None


@dataclass(slots=True)
class BootStatus:
    """High-level boot integration status for DBLM."""

    detected: str
    is_uefi: bool
    grub: GrubStatus
    systemd_boot: SystemdBootStatus


def is_uefi_boot() -> bool:
    """Return True if the current system appears to be booted in UEFI mode."""
    return Path("/sys/firmware/efi").exists()


def systemd_unit_state(unit_name: str) -> str | None:
    """Return a best-effort systemd unit state."""
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


def grub_cfg_candidates() -> list[str]:
    """Return likely GRUB configuration output paths."""
    candidates = [
        "/boot/grub/grub.cfg",
        "/boot/grub2/grub.cfg",
        "/efi/EFI/debian/grub.cfg",
    ]
    return [path for path in candidates if Path(path).exists()]


def detect_grub_status() -> GrubStatus:
    """Detect the presence of GRUB tooling and common config paths."""
    grub_install = command_exists("grub-install")
    grub_mkconfig = command_exists("grub-mkconfig")
    grub_btrfsd = command_exists("grub-btrfsd")

    status = GrubStatus(
        available=grub_install or grub_mkconfig,
        grub_install=grub_install,
        grub_mkconfig=grub_mkconfig,
        grub_cfg_paths=grub_cfg_candidates(),
        grub_btrfsd=grub_btrfsd,
        grub_btrfs_path_unit=systemd_unit_state("grub-btrfs.path"),
        grub_btrfs_service_unit=systemd_unit_state("grub-btrfs.service"),
    )
    LOGGER.info(
        "Detected GRUB status (available=%s, mkconfig=%s, grub-btrfsd=%s).",
        status.available,
        status.grub_mkconfig,
        status.grub_btrfsd,
    )
    return status


def bootctl_version() -> str | None:
    """Return the first bootctl version line."""
    if not command_exists("bootctl"):
        return None

    result = run_command(["bootctl", "--version"], check=False)
    if not result.ok and not result.stdout:
        return None

    first_line = result.stdout.splitlines()[0] if result.stdout else ""
    return first_line.strip() or None


def bootctl_is_installed() -> bool:
    """Return True when bootctl reports a systemd-boot installation."""
    if not command_exists("bootctl"):
        return False

    result = run_command(["bootctl", "is-installed"], check=False)
    return result.ok


def detect_efi_mountpoint() -> str | None:
    """Return a likely EFI mountpoint if it exists."""
    candidates = ["/boot/efi", "/efi", "/boot"]
    for candidate in candidates:
        path = Path(candidate)
        if path.exists() and path.is_dir():
            return candidate
    return None


def detect_systemd_boot_status() -> SystemdBootStatus:
    """Detect the presence and installation status of systemd-boot."""
    available = command_exists("bootctl")
    efi_mountpoint = detect_efi_mountpoint()

    loader_entries_dir = None
    if efi_mountpoint:
        candidate = Path(efi_mountpoint) / "loader" / "entries"
        if candidate.exists():
            loader_entries_dir = str(candidate)

    status = SystemdBootStatus(
        available=available,
        installed=bootctl_is_installed() if available else False,
        version=bootctl_version(),
        efi_mountpoint=efi_mountpoint,
        loader_entries_dir=loader_entries_dir,
    )
    LOGGER.info(
        "Detected systemd-boot status (available=%s, installed=%s, efi=%s).",
        status.available,
        status.installed,
        status.efi_mountpoint,
    )
    return status


def detect_boot_status() -> BootStatus:
    """Collect a high-level boot integration status."""
    grub = detect_grub_status()
    systemd_boot = detect_systemd_boot_status()
    uefi = is_uefi_boot()

    detected = "unknown"
    if systemd_boot.available and systemd_boot.installed:
        detected = "systemd-boot"
    elif grub.available:
        detected = "grub"
    elif uefi:
        detected = "uefi-unknown"

    status = BootStatus(
        detected=detected,
        is_uefi=uefi,
        grub=grub,
        systemd_boot=systemd_boot,
    )
    LOGGER.info("Detected boot status: %s", status.detected)
    return status


def regenerate_grub(
    config_path: str | None = None,
    *,
    operation_log: OperationLogger | None = None,
) -> bool:
    """
    Regenerate GRUB configuration.

    If config_path is omitted, DBLM uses a common default path.
    """
    log = operation_log or _noop_operation_logger

    if not command_exists("grub-mkconfig"):
        raise RuntimeError("grub-mkconfig is not available.")

    if config_path is None:
        candidates = grub_cfg_candidates()
        config_path = candidates[0] if candidates else "/boot/grub/grub.cfg"

    LOGGER.info("Regenerating GRUB config at %s", config_path)
    log(f"Regenerating GRUB configuration at {config_path}", "info", "grub")
    result = run_command(
        ["grub-mkconfig", "-o", config_path],
        check=False,
    )
    if result.ok:
        log("GRUB configuration regenerated successfully.", "info", "grub")
    else:
        log("Failed to regenerate GRUB configuration.", "error", "grub")
    return result.ok


def enable_grub_btrfs(*, operation_log: OperationLogger | None = None) -> bool:
    """Enable grub-btrfs path monitoring if available."""
    log = operation_log or _noop_operation_logger

    if not command_exists("systemctl"):
        raise RuntimeError("systemctl is not available.")
    LOGGER.info("Enabling grub-btrfs.path")
    log("Enabling grub-btrfs.path.", "info", "grub-btrfs")
    result = run_command(["systemctl", "enable", "--now", "grub-btrfs.path"], check=False)
    if result.ok:
        log("grub-btrfs.path enabled successfully.", "info", "grub-btrfs")
    else:
        log("Failed to enable grub-btrfs.path.", "error", "grub-btrfs")
    return result.ok


def disable_grub_btrfs(*, operation_log: OperationLogger | None = None) -> bool:
    """Disable grub-btrfs path monitoring if available."""
    log = operation_log or _noop_operation_logger

    if not command_exists("systemctl"):
        raise RuntimeError("systemctl is not available.")
    LOGGER.info("Disabling grub-btrfs.path")
    log("Disabling grub-btrfs.path.", "warning", "grub-btrfs")
    result = run_command(["systemctl", "disable", "--now", "grub-btrfs.path"], check=False)
    if result.ok:
        log("grub-btrfs.path disabled successfully.", "info", "grub-btrfs")
    else:
        log("Failed to disable grub-btrfs.path.", "error", "grub-btrfs")
    return result.ok


def install_systemd_boot(
    efi_path: str | None = None,
    *,
    operation_log: OperationLogger | None = None,
) -> bool:
    """
    Install systemd-boot using bootctl.

    This only handles the basic install step.
    """
    log = operation_log or _noop_operation_logger

    if not command_exists("bootctl"):
        raise RuntimeError("bootctl is not available.")

    command = ["bootctl", "install"]
    if efi_path:
        command.extend(["--esp-path", efi_path])

    LOGGER.info("Installing systemd-boot (efi_path=%s)", efi_path)
    log("Installing systemd-boot.", "info", "systemd-boot")
    result = run_command(command, check=False)
    if result.ok:
        log("systemd-boot installed successfully.", "info", "systemd-boot")
    else:
        log("Failed to install systemd-boot.", "error", "systemd-boot")
    return result.ok


def update_systemd_boot(
    efi_path: str | None = None,
    *,
    operation_log: OperationLogger | None = None,
) -> bool:
    """Update an existing systemd-boot installation."""
    log = operation_log or _noop_operation_logger

    if not command_exists("bootctl"):
        raise RuntimeError("bootctl is not available.")

    command = ["bootctl", "update"]
    if efi_path:
        command.extend(["--esp-path", efi_path])

    LOGGER.info("Updating systemd-boot (efi_path=%s)", efi_path)
    log("Updating systemd-boot.", "info", "systemd-boot")
    result = run_command(command, check=False)
    if result.ok:
        log("systemd-boot updated successfully.", "info", "systemd-boot")
    else:
        log("Failed to update systemd-boot.", "error", "systemd-boot")
    return result.ok


def ensure_loader_entries_dir(
    efi_mountpoint: str,
    *,
    operation_log: OperationLogger | None = None,
) -> Path:
    """Ensure the loader entries directory exists."""
    log = operation_log or _noop_operation_logger
    entries_dir = Path(efi_mountpoint) / "loader" / "entries"
    entries_dir.mkdir(parents=True, exist_ok=True)
    LOGGER.info("Ensured loader entries directory exists: %s", entries_dir)
    log(f"Ensured loader entries directory exists: {entries_dir}", "info", "systemd-boot")
    return entries_dir


def write_systemd_boot_entry(
    *,
    efi_mountpoint: str,
    entry_name: str,
    title: str,
    linux_path: str,
    initrd_path: str | None = None,
    options: str = "",
    operation_log: OperationLogger | None = None,
) -> Path:
    """
    Write a basic systemd-boot loader entry.

    This is intentionally simple and does not yet generate snapshot-specific entries.
    """
    log = operation_log or _noop_operation_logger
    entries_dir = ensure_loader_entries_dir(efi_mountpoint, operation_log=operation_log)
    entry_path = entries_dir / f"{entry_name}.conf"

    lines = [
        f"title   {title}",
        f"linux   {linux_path}",
    ]
    if initrd_path:
        lines.append(f"initrd  {initrd_path}")
    if options:
        lines.append(f"options {options}")

    entry_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    LOGGER.info("Wrote systemd-boot entry: %s", entry_path)
    log(f"Wrote systemd-boot entry {entry_path.name}", "info", "systemd-boot")
    return entry_path


def delete_systemd_boot_entry(
    *,
    efi_mountpoint: str,
    entry_name: str,
    missing_ok: bool = True,
    operation_log: OperationLogger | None = None,
) -> Path:
    """Delete a loader entry file."""
    log = operation_log or _noop_operation_logger
    entry_path = Path(efi_mountpoint) / "loader" / "entries" / f"{entry_name}.conf"
    if entry_path.exists():
        entry_path.unlink()
        LOGGER.info("Deleted systemd-boot entry: %s", entry_path)
        log(f"Deleted systemd-boot entry {entry_path.name}", "info", "systemd-boot")
    elif not missing_ok:
        raise FileNotFoundError(f"Loader entry not found: {entry_path}")
    return entry_path


def validate_boot_integration() -> list[str]:
    """Return high-level warnings related to boot integration."""
    warnings: list[str] = []
    status = detect_boot_status()

    if status.detected == "unknown":
        warnings.append("Bootloader could not be identified confidently.")

    if status.is_uefi and not status.systemd_boot.efi_mountpoint:
        warnings.append("UEFI appears to be active, but no EFI mountpoint was detected.")

    if status.detected == "grub" and not status.grub.grub_mkconfig:
        warnings.append("GRUB appears to be in use, but grub-mkconfig is missing.")

    if status.grub.grub_btrfsd and status.grub.grub_btrfs_path_unit in {"not found", "disabled"}:
        warnings.append("grub-btrfs tooling exists, but its systemd integration is not enabled.")

    if status.systemd_boot.available and not status.is_uefi:
        warnings.append("bootctl exists, but the system does not appear to be booted in UEFI mode.")

    if warnings:
        LOGGER.warning("Boot integration validation produced %s warning(s).", len(warnings))
    else:
        LOGGER.info("Boot integration validation produced no warnings.")
    return warnings
