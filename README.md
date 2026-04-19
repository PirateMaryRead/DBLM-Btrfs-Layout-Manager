# DBLM — Btrfs Layout Manager

DBLM is an interactive terminal user interface for auditing and managing Btrfs layouts on existing Linux installations.

It is designed for systems that already use Btrfs and need a safer way to reorganize subvolumes, migrate mutable directories, prepare Snapper-compatible layouts, and inspect boot integration options.

## Features

- Audit the current Btrfs layout
- Detect root and `/home` filesystem topology
- Handle `/home` when it is part of the same Btrfs filesystem or a separate Btrfs filesystem
- Plan and manage common subvolumes
- Track backups and rollback metadata
- Restore backups and delete backups
- Inspect Snapper readiness
- Inspect GRUB, grub-btrfs, and systemd-boot integration points
- Review changes before destructive operations

## Supported targets

DBLM is designed to manage targets such as:

- `/.snapshots`
- `/root`
- `/home` when `/home` is Btrfs-capable
- `/tmp`
- `/var/log`
- `/var/cache`
- `/var/tmp`
- `/var/lib/flatpak`
- `/var/lib/libvirt`
- `/var/lib/containers`
- `/var/lib/waydroid`

## `/home` handling

DBLM does not assume that `/home` belongs to the same filesystem as `/`.

During the audit phase it detects whether `/home` is:

- part of the same Btrfs filesystem as `/`
- a separate Btrfs filesystem
- a separate non-Btrfs filesystem
- missing or using an unusual layout

If `/home` is a separate Btrfs filesystem, DBLM treats it as its own manageable scope.

If `/home` is mounted separately on a non-Btrfs filesystem, DBLM keeps system-level management available while disabling home subvolume operations.

## Profiles

DBLM includes reusable target profiles:

### Minimal Snapper

- `/.snapshots`
- `/root`
- `/var/log`

### Desktop

- minimal profile
- `/home` when Btrfs-capable
- `/var/cache`
- `/var/tmp`

### Containers and Apps

- `/var/lib/flatpak`
- `/var/lib/libvirt`
- `/var/lib/containers`
- `/var/lib/waydroid`

### Complete

- all previous profiles
- `/tmp`

## Interface

DBLM uses a single-screen terminal interface with keyboard navigation.

Main sections:

- Dashboard
- Dependencies
- Subvolumes
- Snapper
- Boot
- Plan
- Apply
- Revert
- Backups

## Project structure

```text
dblm-btrfs-layout-manager/
├─ app.py
├─ core/
│  ├─ __init__.py
│  ├─ system.py
│  ├─ state.py
│  ├─ profiles.py
│  ├─ btrfs.py
│  ├─ fstab.py
│  ├─ packages.py
│  ├─ migrate.py
│  ├─ snapper.py
│  └─ boot.py
├─ ui/
│  ├─ __init__.py
│  ├─ styles.tcss
│  ├─ screens/
│  │  ├─ __init__.py
│  │  ├─ dashboard.py
│  │  ├─ dependencies.py
│  │  ├─ subvolumes.py
│  │  ├─ snapper.py
│  │  ├─ boot.py
│  │  ├─ plan.py
│  │  ├─ apply.py
│  │  ├─ rollback.py
│  │  └─ backups.py
│  └─ widgets/
│     ├─ __init__.py
│     ├─ summary_box.py
│     ├─ log_view.py
│     ├─ status_list.py
│     └─ plan_table.py
├─ data/
│  ├─ state.json
│  └─ logs/
├─ pyproject.toml
├─ .gitignore
└─ README.md
