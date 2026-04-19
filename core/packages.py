from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from core.system import command_exists, run_command


@dataclass(slots=True)
class PackageRequirement:
    """Represents a package and the feature it belongs to."""

    package: str
    required: bool = True
    feature: str = "core"
    description: str = ""


@dataclass(slots=True)
class PackageCheckResult:
    """Represents the availability of a package or binary."""

    package: str
    installed: bool
    feature: str = "core"
    required: bool = True
    description: str = ""


@dataclass(slots=True)
class AptStatus:
    """Represents APT availability and capabilities."""

    has_apt: bool
    has_apt_get: bool
    has_dpkg_query: bool
    usable: bool

    @property
    def can_install(self) -> bool:
        return self.has_apt_get and self.has_dpkg_query


@dataclass(slots=True)
class InstallPlan:
    """Package installation plan."""

    to_install: list[str] = field(default_factory=list)
    already_installed: list[str] = field(default_factory=list)
    missing_apt_support: bool = False

    @property
    def is_empty(self) -> bool:
        return not self.to_install


CORE_PACKAGES: tuple[PackageRequirement, ...] = (
    PackageRequirement(
        package="btrfs-progs",
        required=True,
        feature="core",
        description="Required for subvolume and filesystem operations.",
    ),
    PackageRequirement(
        package="rsync",
        required=True,
        feature="core",
        description="Required for directory migration and backup copy operations.",
    ),
    PackageRequirement(
        package="util-linux",
        required=True,
        feature="core",
        description="Provides findmnt, mount, and related utilities.",
    ),
)

SNAPPER_PACKAGES: tuple[PackageRequirement, ...] = (
    PackageRequirement(
        package="snapper",
        required=False,
        feature="snapper",
        description="Snapper integration and snapshot management.",
    ),
)

GRUB_PACKAGES: tuple[PackageRequirement, ...] = (
    PackageRequirement(
        package="grub-common",
        required=False,
        feature="boot",
        description="Common GRUB tooling.",
    ),
)

SYSTEMD_BOOT_PACKAGES: tuple[PackageRequirement, ...] = (
    PackageRequirement(
        package="systemd-boot",
        required=False,
        feature="boot",
        description="systemd-boot integration.",
    ),
)

OPTIONAL_PACKAGES: tuple[PackageRequirement, ...] = (
    PackageRequirement(
        package="grub-btrfs",
        required=False,
        feature="boot",
        description="Optional GRUB snapshot menu integration.",
    ),
)

BINARY_TO_PACKAGE_MAP: dict[str, str] = {
    "btrfs": "btrfs-progs",
    "rsync": "rsync",
    "findmnt": "util-linux",
    "mount": "util-linux",
    "umount": "util-linux",
    "snapper": "snapper",
    "grub-mkconfig": "grub-common",
    "bootctl": "systemd-boot",
}


def get_apt_status() -> AptStatus:
    """Inspect whether APT tooling is available."""
    has_apt = command_exists("apt")
    has_apt_get = command_exists("apt-get")
    has_dpkg_query = command_exists("dpkg-query")

    return AptStatus(
        has_apt=has_apt,
        has_apt_get=has_apt_get,
        has_dpkg_query=has_dpkg_query,
        usable=(has_apt or has_apt_get) and has_dpkg_query,
    )


def dpkg_package_installed(package_name: str) -> bool:
    """Return True when dpkg reports a package as installed."""
    if not command_exists("dpkg-query"):
        return False

    result = run_command(
        ["dpkg-query", "-W", "-f=${Status}", package_name],
        check=False,
    )
    if not result.ok:
        return False

    return "install ok installed" in result.stdout


def check_packages(requirements: Iterable[PackageRequirement]) -> list[PackageCheckResult]:
    """Check package installation state through dpkg-query."""
    checks: list[PackageCheckResult] = []

    for requirement in requirements:
        checks.append(
            PackageCheckResult(
                package=requirement.package,
                installed=dpkg_package_installed(requirement.package),
                feature=requirement.feature,
                required=requirement.required,
                description=requirement.description,
            )
        )

    return checks


def build_feature_requirements(
    *,
    include_snapper: bool = False,
    include_grub: bool = False,
    include_systemd_boot: bool = False,
    include_optional: bool = False,
) -> list[PackageRequirement]:
    """Build the package requirement list for selected features."""
    requirements: list[PackageRequirement] = list(CORE_PACKAGES)

    if include_snapper:
        requirements.extend(SNAPPER_PACKAGES)

    if include_grub:
        requirements.extend(GRUB_PACKAGES)

    if include_systemd_boot:
        requirements.extend(SYSTEMD_BOOT_PACKAGES)

    if include_optional:
        requirements.extend(OPTIONAL_PACKAGES)

    # Deduplicate while preserving order.
    seen: set[str] = set()
    unique: list[PackageRequirement] = []
    for item in requirements:
        if item.package in seen:
            continue
        seen.add(item.package)
        unique.append(item)

    return unique


def build_install_plan(requirements: Iterable[PackageRequirement]) -> InstallPlan:
    """Build an install plan from package requirements."""
    apt_status = get_apt_status()
    checks = check_packages(requirements)

    plan = InstallPlan(
        missing_apt_support=not apt_status.can_install,
    )

    for item in checks:
        if item.installed:
            plan.already_installed.append(item.package)
        else:
            plan.to_install.append(item.package)

    return plan


def apt_update() -> bool:
    """Run apt-get update."""
    apt_status = get_apt_status()
    if not apt_status.can_install:
        raise RuntimeError("APT tooling is not available on this system.")

    result = run_command(["apt-get", "update"], check=False)
    return result.ok


def apt_install(
    packages: list[str],
    *,
    assume_yes: bool = True,
    no_recommends: bool = False,
) -> bool:
    """Install packages using apt-get."""
    if not packages:
        return True

    apt_status = get_apt_status()
    if not apt_status.can_install:
        raise RuntimeError("APT tooling is not available on this system.")

    command = ["apt-get", "install"]
    if assume_yes:
        command.append("-y")
    if no_recommends:
        command.append("--no-install-recommends")
    command.extend(packages)

    result = run_command(command, check=False)
    return result.ok


def ensure_packages_installed(
    requirements: Iterable[PackageRequirement],
    *,
    update_first: bool = True,
    assume_yes: bool = True,
    no_recommends: bool = False,
) -> InstallPlan:
    """
    Ensure packages for the selected features are installed.

    Returns the computed install plan whether or not installation was needed.
    """
    plan = build_install_plan(requirements)

    if plan.is_empty:
        return plan

    if plan.missing_apt_support:
        raise RuntimeError("Cannot install packages automatically because APT support is unavailable.")

    if update_first:
        updated = apt_update()
        if not updated:
            raise RuntimeError("apt-get update failed.")

    installed = apt_install(
        plan.to_install,
        assume_yes=assume_yes,
        no_recommends=no_recommends,
    )
    if not installed:
        raise RuntimeError("apt-get install failed.")

    return build_install_plan(requirements)


def summarize_package_checks(checks: Iterable[PackageCheckResult]) -> dict[str, list[str]]:
    """Summarize package checks in a UI-friendly structure."""
    installed: list[str] = []
    missing_required: list[str] = []
    missing_optional: list[str] = []

    for item in checks:
        if item.installed:
            installed.append(item.package)
        elif item.required:
            missing_required.append(item.package)
        else:
            missing_optional.append(item.package)

    return {
        "installed": installed,
        "missing_required": missing_required,
        "missing_optional": missing_optional,
    }


def package_for_binary(binary: str) -> str | None:
    """Return the Debian package that most likely provides a binary."""
    return BINARY_TO_PACKAGE_MAP.get(binary)


def infer_missing_packages_from_binaries(binaries: Iterable[str]) -> list[str]:
    """Map missing binaries to likely package names."""
    packages: list[str] = []
    seen: set[str] = set()

    for binary in binaries:
        package = package_for_binary(binary)
        if package is None or package in seen:
            continue
        seen.add(package)
        packages.append(package)

    return packages
