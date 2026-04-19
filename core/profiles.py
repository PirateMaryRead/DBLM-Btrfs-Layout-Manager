from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class SubvolumeTarget:
    """A mountpoint that DBLM can manage as a Btrfs subvolume."""

    key: str
    path: str
    suggested_name_flat: str
    description: str
    scope: str = "system"
    enabled_by_default: bool = False
    requires_btrfs_home: bool = False
    risky: bool = False

    def suggested_name(self, *, flat_layout: bool = True) -> str:
        """
        Return the suggested subvolume name for the detected layout style.

        For now DBLM officially targets flat naming first, but this method keeps
        the interface ready for nested naming later.
        """
        if flat_layout:
            return self.suggested_name_flat

        # Basic nested fallback for future support.
        if self.path == "/":
            return "@"
        if self.path == "/.snapshots":
            return "@/.snapshots"
        return f"@{self.path}"


@dataclass(frozen=True, slots=True)
class Profile:
    """A reusable set of subvolume targets."""

    key: str
    name: str
    description: str
    target_keys: tuple[str, ...] = field(default_factory=tuple)


SYSTEM_TARGETS: dict[str, SubvolumeTarget] = {
    "snapshots": SubvolumeTarget(
        key="snapshots",
        path="/.snapshots",
        suggested_name_flat="@snapshots",
        description="Stores Snapper snapshots outside the root subvolume.",
        scope="system",
        enabled_by_default=True,
    ),
    "root-home": SubvolumeTarget(
        key="root-home",
        path="/root",
        suggested_name_flat="@root",
        description="Separates the root user's home directory from the root subvolume.",
        scope="system",
        enabled_by_default=True,
    ),
    "tmp": SubvolumeTarget(
        key="tmp",
        path="/tmp",
        suggested_name_flat="@tmp",
        description="Makes /tmp independent from the root subvolume.",
        scope="system",
        enabled_by_default=False,
        risky=True,
    ),
    "var-log": SubvolumeTarget(
        key="var-log",
        path="/var/log",
        suggested_name_flat="@var@log",
        description="Keeps logs outside the main root snapshot scope.",
        scope="system",
        enabled_by_default=True,
    ),
    "var-cache": SubvolumeTarget(
        key="var-cache",
        path="/var/cache",
        suggested_name_flat="@var@cache",
        description="Keeps mutable cache data out of root snapshots.",
        scope="system",
        enabled_by_default=False,
    ),
    "var-tmp": SubvolumeTarget(
        key="var-tmp",
        path="/var/tmp",
        suggested_name_flat="@var@tmp",
        description="Separates persistent temporary data from root snapshots.",
        scope="system",
        enabled_by_default=False,
    ),
    "flatpak": SubvolumeTarget(
        key="flatpak",
        path="/var/lib/flatpak",
        suggested_name_flat="@var@lib@flatpak",
        description="Stores system Flatpak data in its own subvolume.",
        scope="system",
        enabled_by_default=False,
    ),
    "libvirt": SubvolumeTarget(
        key="libvirt",
        path="/var/lib/libvirt",
        suggested_name_flat="@var@lib@libvirt",
        description="Separates libvirt data and VM assets from root snapshots.",
        scope="system",
        enabled_by_default=False,
    ),
    "containers": SubvolumeTarget(
        key="containers",
        path="/var/lib/containers",
        suggested_name_flat="@var@lib@containers",
        description="Separates container storage from the root subvolume.",
        scope="system",
        enabled_by_default=False,
    ),
    "waydroid": SubvolumeTarget(
        key="waydroid",
        path="/var/lib/waydroid",
        suggested_name_flat="@var@lib@waydroid",
        description="Separates Waydroid data from the root snapshot scope.",
        scope="system",
        enabled_by_default=False,
    ),
}

HOME_TARGETS: dict[str, SubvolumeTarget] = {
    "home": SubvolumeTarget(
        key="home",
        path="/home",
        suggested_name_flat="@home",
        description="Separates /home when it is part of the same Btrfs filesystem or a separate Btrfs filesystem.",
        scope="home",
        enabled_by_default=False,
        requires_btrfs_home=True,
    ),
}

ALL_TARGETS: dict[str, SubvolumeTarget] = {
    **SYSTEM_TARGETS,
    **HOME_TARGETS,
}


PROFILES: dict[str, Profile] = {
    "minimal-snapper": Profile(
        key="minimal-snapper",
        name="Minimal Snapper",
        description="Minimal layout for snapshot-oriented systems.",
        target_keys=(
            "snapshots",
            "root-home",
            "var-log",
        ),
    ),
    "desktop": Profile(
        key="desktop",
        name="Desktop",
        description="Common desktop layout with cache and temporary separation.",
        target_keys=(
            "snapshots",
            "root-home",
            "var-log",
            "var-cache",
            "var-tmp",
            "home",
        ),
    ),
    "containers-and-apps": Profile(
        key="containers-and-apps",
        name="Containers and Apps",
        description="Useful for systems using Flatpak, containers, libvirt, and Waydroid.",
        target_keys=(
            "flatpak",
            "libvirt",
            "containers",
            "waydroid",
        ),
    ),
    "complete": Profile(
        key="complete",
        name="Complete",
        description="Broad layout covering snapshots, caches, apps, and optional home handling.",
        target_keys=(
            "snapshots",
            "root-home",
            "tmp",
            "var-log",
            "var-cache",
            "var-tmp",
            "flatpak",
            "libvirt",
            "containers",
            "waydroid",
            "home",
        ),
    ),
}


def get_target(key: str) -> SubvolumeTarget:
    """Return a target by key."""
    try:
        return ALL_TARGETS[key]
    except KeyError as exc:
        raise KeyError(f"Unknown target key: {key}") from exc


def get_profile(key: str) -> Profile:
    """Return a profile by key."""
    try:
        return PROFILES[key]
    except KeyError as exc:
        raise KeyError(f"Unknown profile key: {key}") from exc


def list_profiles() -> list[Profile]:
    """Return all profiles in insertion order."""
    return list(PROFILES.values())


def list_targets(*, include_home: bool = True) -> list[SubvolumeTarget]:
    """Return all known targets."""
    if include_home:
        return list(ALL_TARGETS.values())
    return list(SYSTEM_TARGETS.values())


def list_system_targets() -> list[SubvolumeTarget]:
    """Return system-scoped targets only."""
    return list(SYSTEM_TARGETS.values())


def list_home_targets() -> list[SubvolumeTarget]:
    """Return home-scoped targets only."""
    return list(HOME_TARGETS.values())


def resolve_profile_targets(
    profile_key: str,
    *,
    include_home: bool,
) -> list[SubvolumeTarget]:
    """
    Resolve a profile into target objects.

    Home targets are automatically filtered when /home is not Btrfs-capable.
    """
    profile = get_profile(profile_key)
    resolved: list[SubvolumeTarget] = []

    for key in profile.target_keys:
        target = get_target(key)
        if target.scope == "home" and not include_home:
            continue
        resolved.append(target)

    return resolved


def default_targets(*, include_home: bool = False) -> list[SubvolumeTarget]:
    """Return targets enabled by default for a first-pass UI selection."""
    items = list_targets(include_home=include_home)
    return [target for target in items if target.enabled_by_default]


def filter_targets_for_home_support(
    targets: list[SubvolumeTarget],
    *,
    home_is_btrfs: bool,
) -> list[SubvolumeTarget]:
    """Remove targets that require a Btrfs-capable /home when unavailable."""
    if home_is_btrfs:
        return list(targets)
    return [target for target in targets if not target.requires_btrfs_home]


def group_targets_by_scope(
    targets: list[SubvolumeTarget],
) -> dict[str, list[SubvolumeTarget]]:
    """Group targets by logical filesystem scope."""
    grouped: dict[str, list[SubvolumeTarget]] = {
        "system": [],
        "home": [],
    }
    for target in targets:
        grouped.setdefault(target.scope, []).append(target)
    return grouped
