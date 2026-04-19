from __future__ import annotations

from dataclasses import dataclass, field
import os
import platform
import shlex
import shutil
import subprocess
from typing import Sequence


class CommandError(RuntimeError):
    """Raised when an external command fails."""


@dataclass(slots=True)
class CommandResult:
    """Normalized result for an executed command."""

    command: list[str]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


@dataclass(slots=True)
class FilesystemContext:
    """Represents a mountpoint and its filesystem details."""

    mountpoint: str
    source: str = ""
    fstype: str = ""
    options: str = ""
    uuid: str = ""
    subvol: str | None = None
    subvolid: str | None = None
    same_device_as_root: bool | None = None
    exists: bool = True
    separately_mounted: bool = False
    is_btrfs: bool = False

    @property
    def is_separate_btrfs(self) -> bool:
        return self.separately_mounted and self.is_btrfs

    @property
    def is_same_btrfs_as_root(self) -> bool:
        return bool(self.is_btrfs and self.same_device_as_root)

    @property
    def home_supports_subvolumes(self) -> bool:
        return self.mountpoint == "/home" and self.is_btrfs

    @property
    def display_name(self) -> str:
        if not self.exists:
            return f"{self.mountpoint} (missing)"
        if self.is_same_btrfs_as_root:
            return f"{self.mountpoint} (same Btrfs filesystem as /)"
        if self.is_separate_btrfs:
            return f"{self.mountpoint} (separate Btrfs filesystem)"
        if self.separately_mounted:
            return f"{self.mountpoint} (separate {self.fstype} filesystem)"
        return f"{self.mountpoint} ({self.fstype or 'unknown'})"


@dataclass(slots=True)
class BootloaderStatus:
    """Detected bootloader tooling and environment."""

    detected: str = "unknown"
    is_uefi: bool = False
    has_grub: bool = False
    has_grub_mkconfig: bool = False
    has_bootctl: bool = False
    has_systemd_boot: bool = False
    has_grub_btrfsd: bool = False
    efi_mountpoint: str | None = None


@dataclass(slots=True)
class DependencyStatus:
    """Binary-level dependency summary."""

    required_ok: bool
    missing_required: list[str] = field(default_factory=list)
    optional_found: list[str] = field(default_factory=list)
    missing_optional: list[str] = field(default_factory=list)


@dataclass(slots=True)
class EnvironmentSnapshot:
    """High-level system snapshot used by the app UI."""

    hostname: str
    kernel: str
    distro: str
    is_root: bool
    root_fs: FilesystemContext
    home_fs: FilesystemContext
    bootloader: BootloaderStatus
    dependencies: DependencyStatus
    warnings: list[str] = field(default_factory=list)


REQUIRED_COMMANDS: tuple[str, ...] = (
    "findmnt",
    "btrfs",
    "rsync",
    "mount",
    "umount",
    "awk",
    "sed",
    "grep",
)

OPTIONAL_COMMANDS: tuple[str, ...] = (
    "snapper",
    "bootctl",
    "grub-mkconfig",
    "grub-btrfsd",
    "apt",
    "systemctl",
)


def run_command(
    command: Sequence[str],
    *,
    check: bool = False,
    env: dict[str, str] | None = None,
) -> CommandResult:
    """Run a command and return a normalized result."""
    completed = subprocess.run(
        list(command),
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    result = CommandResult(
        command=list(command),
        returncode=completed.returncode,
        stdout=completed.stdout.strip(),
        stderr=completed.stderr.strip(),
    )
    if check and not result.ok:
        joined = " ".join(shlex.quote(part) for part in result.command)
        raise CommandError(
            f"Command failed ({result.returncode}): {joined}\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )
    return result


def command_exists(binary: str) -> bool:
    """Return True when a binary exists in PATH."""
    return shutil.which(binary) is not None


def require_root() -> None:
    """Raise PermissionError when the process is not running as root."""
    if os.geteuid() != 0:
        raise PermissionError("DBLM requires root privileges for system changes.")


def read_os_release() -> dict[str, str]:
    """Read /etc/os-release into a dict."""
    data: dict[str, str] = {}
    path = "/etc/os-release"
    if not os.path.exists(path):
        return data

    with open(path, "r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            data[key] = value.strip().strip('"')
    return data


def get_distro_label() -> str:
    """Return a human-friendly distro label."""
    os_release = read_os_release()
    return (
        os_release.get("PRETTY_NAME")
        or os_release.get("NAME")
        or platform.platform()
    )


def _parse_mount_options(options: str) -> tuple[str | None, str | None]:
    subvol = None
    subvolid = None
    for item in options.split(","):
        item = item.strip()
        if item.startswith("subvol="):
            subvol = item.split("=", 1)[1]
        elif item.startswith("subvolid="):
            subvolid = item.split("=", 1)[1]
    return subvol, subvolid


def _parse_findmnt_pairs(stdout: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for token in shlex.split(stdout):
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        values[key] = value
    return values


def get_mount_context(mountpoint: str) -> FilesystemContext:
    """
    Inspect a mountpoint using findmnt.

    Uses key-value output to avoid fragile whitespace parsing.
    Returns a best-effort FilesystemContext. Missing mountpoints are handled.
    """
    if not os.path.exists(mountpoint):
        return FilesystemContext(mountpoint=mountpoint, exists=False)

    result = run_command([
        "findmnt",
        "-P",
        "-n",
        "-o",
        "SOURCE,FSTYPE,OPTIONS,UUID,TARGET",
        mountpoint,
    ])
    if not result.ok or not result.stdout:
        return FilesystemContext(mountpoint=mountpoint, exists=os.path.exists(mountpoint))

    values = _parse_findmnt_pairs(result.stdout)
    source = values.get("SOURCE", "")
    fstype = values.get("FSTYPE", "")
    options = values.get("OPTIONS", "")
    uuid = values.get("UUID", "")
    target = values.get("TARGET", "")
    subvol, subvolid = _parse_mount_options(options)
    separately_mounted = target == mountpoint and mountpoint != "/"

    return FilesystemContext(
        mountpoint=mountpoint,
        source=source,
        fstype=fstype,
        options=options,
        uuid=uuid,
        subvol=subvol,
        subvolid=subvolid,
        exists=True,
        separately_mounted=separately_mounted,
        is_btrfs=(fstype == "btrfs"),
    )

def detect_root_context() -> FilesystemContext:
    """Inspect the root filesystem context."""
    root_ctx = get_mount_context("/")
    if not root_ctx.exists:
        raise RuntimeError("Root mountpoint / does not exist.")
    return root_ctx


def detect_home_context(root_ctx: FilesystemContext | None = None) -> FilesystemContext:
    """Inspect /home and determine whether it is the same or a separate filesystem."""
    root_ctx = root_ctx or detect_root_context()
    home_ctx = get_mount_context("/home")
    if not home_ctx.exists:
        return home_ctx

    same_device = None
    if root_ctx.source and home_ctx.source:
        same_device = root_ctx.source == home_ctx.source

    home_ctx.same_device_as_root = same_device

    # If /home is not a separate mount, treat it as part of the root filesystem.
    if not home_ctx.separately_mounted:
        home_ctx.source = root_ctx.source
        home_ctx.fstype = root_ctx.fstype
        home_ctx.uuid = root_ctx.uuid
        home_ctx.options = root_ctx.options
        home_ctx.subvol = root_ctx.subvol
        home_ctx.subvolid = root_ctx.subvolid
        home_ctx.is_btrfs = root_ctx.is_btrfs
        home_ctx.same_device_as_root = True

    return home_ctx


def detect_bootloader() -> BootloaderStatus:
    """Best-effort bootloader detection."""
    is_uefi = os.path.exists("/sys/firmware/efi")
    has_grub = command_exists("grub-install")
    has_grub_mkconfig = command_exists("grub-mkconfig")
    has_bootctl = command_exists("bootctl")
    has_grub_btrfsd = command_exists("grub-btrfsd")

    efi_ctx = get_mount_context("/boot/efi")
    efi_mountpoint = "/boot/efi" if efi_ctx.exists and efi_ctx.source else None

    detected = "unknown"
    if has_bootctl and is_uefi:
        status = run_command(["bootctl", "is-installed"])
        if status.ok:
            detected = "systemd-boot"
    if detected == "unknown" and (has_grub or has_grub_mkconfig):
        detected = "grub"
    if detected == "unknown" and is_uefi:
        detected = "uefi-unknown"

    return BootloaderStatus(
        detected=detected,
        is_uefi=is_uefi,
        has_grub=has_grub,
        has_grub_mkconfig=has_grub_mkconfig,
        has_bootctl=has_bootctl,
        has_systemd_boot=(detected == "systemd-boot"),
        has_grub_btrfsd=has_grub_btrfsd,
        efi_mountpoint=efi_mountpoint,
    )


def check_dependencies() -> DependencyStatus:
    """Check command-level dependencies used by the app."""
    missing_required = [cmd for cmd in REQUIRED_COMMANDS if not command_exists(cmd)]
    optional_found = [cmd for cmd in OPTIONAL_COMMANDS if command_exists(cmd)]
    missing_optional = [cmd for cmd in OPTIONAL_COMMANDS if not command_exists(cmd)]

    return DependencyStatus(
        required_ok=(len(missing_required) == 0),
        missing_required=missing_required,
        optional_found=optional_found,
        missing_optional=missing_optional,
    )


def collect_warnings(
    root_ctx: FilesystemContext,
    home_ctx: FilesystemContext,
    boot: BootloaderStatus,
    deps: DependencyStatus,
) -> list[str]:
    """Build a list of human-readable warnings for the UI."""
    warnings: list[str] = []

    if root_ctx.fstype != "btrfs":
        warnings.append("Root filesystem is not Btrfs.")
    if not deps.required_ok:
        warnings.append(
            f"Missing required commands: {', '.join(sorted(deps.missing_required))}."
        )
    if home_ctx.exists and not home_ctx.is_btrfs and home_ctx.separately_mounted:
        warnings.append(
            f"/home is mounted separately as {home_ctx.fstype}; "
            "home subvolumes are not available there."
        )
    if home_ctx.exists and home_ctx.is_separate_btrfs:
        warnings.append("/home is a separate Btrfs filesystem and should be handled independently.")
    if boot.detected == "unknown":
        warnings.append("Bootloader could not be identified confidently.")
    if boot.detected == "grub" and not boot.has_grub_mkconfig:
        warnings.append("GRUB detected but grub-mkconfig is not available.")
    return warnings


def scan_environment() -> EnvironmentSnapshot:
    """Collect the current system snapshot for the app."""
    root_ctx = detect_root_context()
    home_ctx = detect_home_context(root_ctx)
    boot = detect_bootloader()
    deps = check_dependencies()

    return EnvironmentSnapshot(
        hostname=platform.node() or "unknown-host",
        kernel=platform.release(),
        distro=get_distro_label(),
        is_root=(os.geteuid() == 0),
        root_fs=root_ctx,
        home_fs=home_ctx,
        bootloader=boot,
        dependencies=deps,
        warnings=collect_warnings(root_ctx, home_ctx, boot, deps),
    )
