# DBLM — Btrfs Layout Manager

An interactive text-based manager for Linux systems using **Btrfs**, focused on:

* safe creation and migration of subvolumes;
* organizing layouts compatible with **Snapper**;
* optional integration with **GRUB**, **grub-btrfs**, and **systemd-boot**;
* temporary backup generation;
* rollback of changes;
* safe review and update of `/etc/fstab`.

This project is primarily designed for Debian-based distributions, with an emphasis on desktop and workstation environments that use Btrfs as the root filesystem.

---

## Goals

This project exists to solve a common problem: many systems are already installed on Btrfs, but without a well-planned subvolume layout. That makes it harder to use:

* snapshots efficiently;
* exclusions for highly mutable directories from the main snapshots;
* Snapper adoption after installation;
* boot integration for snapshots;
* safe migration of heavy directories such as Flatpak, containers, libvirt, and Waydroid.

This manager provides a TUI (Text User Interface) in the terminal to audit the system, plan changes, and execute them more safely.

---

## Key features

### System audit

The application automatically detects:

* the Btrfs root device;
* the UUID of the root partition;
* the subvolume mounted at `/`;
* the current layout pattern;
* existing subvolumes;
* relevant entries in `/etc/fstab`;
* whether `/home` belongs to the same filesystem, is mounted separately, or is unavailable;
* the filesystem type of `/home` when mounted separately;
* whether a separate `/home` is also Btrfs;
* whether Snapper is installed;
* the active bootloader;
* installed dependencies;
* possible conflicts, such as duplicate mountpoints.

### Subvolume management

It can create and migrate subvolumes for directories such as:

* `/.snapshots`
* `/root`
* `/home` when `/home` is on Btrfs or part of the same Btrfs filesystem
* `/tmp`
* `/var/log`
* `/var/cache`
* `/var/tmp`
* `/var/lib/flatpak`
* `/var/lib/libvirt`
* `/var/lib/containers`
* `/var/lib/waydroid`

### Ready-made profiles

Selectable profiles to simplify usage:

* **Minimal Snapper**
* **Desktop**
* **Containers and Apps**
* **Complete**
* **Custom**

### Safe migration

For each selected directory, the app can:

* detect existing content;
* create the corresponding subvolume;
* copy data while preserving attributes;
* create a backup of the previous directory;
* update `fstab`;
* mount and validate the result.

### Snapper

Support for:

* detecting Snapper installation;
* listing existing configurations;
* creating the `root` configuration;
* validating `/.snapshots`;
* enabling timeline and cleanup timers.

### Boot integration

Optional integration with:

* **GRUB**;
* **grub-btrfs**;
* **systemd-boot**.

### Rollback and backups

Operations record:

* created subvolumes;
* migrated directories;
* generated backups;
* `fstab` changes;
* execution state.

This makes it possible to:

* restore original directories;
* revert `fstab` changes;
* unmount and remove newly created subvolumes;
* delete backups after validation.

---

## Interface

The application uses a **single-screen TUI** in the terminal with keyboard navigation.

### Interface structure

* **Top summary bar** with system status;
* **side menu** with the main sections;
* **main panel** with checklists, tables, and actions;
* **footer** with navigation shortcuts.

### Sections

* Dashboard
* Dependencies
* Subvolumes
* Snapper
* Boot
* Plan
* Apply
* Revert
* Backups

---

## Project structure

```text
dblm-btrfs-layout-manager/
├─ app.py
├─ core/
│  ├─ system.py
│  ├─ btrfs.py
│  ├─ migrate.py
│  ├─ fstab.py
│  ├─ snapper.py
│  ├─ boot.py
│  ├─ packages.py
│  ├─ profiles.py
│  └─ state.py
├─ ui/
│  ├─ screens/
│  │  ├─ dashboard.py
│  │  ├─ dependencies.py
│  │  ├─ subvolumes.py
│  │  ├─ snapper.py
│  │  ├─ boot.py
│  │  ├─ plan.py
│  │  ├─ apply.py
│  │  ├─ rollback.py
│  │  └─ backups.py
│  ├─ widgets/
│  │  ├─ summary_box.py
│  │  ├─ status_list.py
│  │  ├─ plan_table.py
│  │  └─ log_view.py
│  └─ styles.tcss
├─ data/
│  ├─ state.json
│  └─ logs/
└─ README.md
```

---

## Architecture

### `app.py`

Entry point for the TUI.

Responsible for:

* initializing the application;
* loading screens;
* keeping global session state;
* coordinating navigation.

### `core/system.py`

System inspection and command execution layer.

Responsible for:

* detecting the environment;
* identifying the Btrfs root;
* detecting `/home` mount topology and filesystem type;
* determining whether `/home` belongs to the same Btrfs filesystem or a separate one;
* detecting the bootloader;
* checking privileges;
* wrapping external commands with logs and error handling.

### `core/btrfs.py`

Responsible for:

* listing subvolumes;
* creating subvolumes;
* checking whether a path is already a subvolume;
* working with more than one Btrfs context when `/home` is separate;
* removing subvolumes safely;
* mounting the top-level subvolume when needed.

### `core/migrate.py`

Responsible for:

* generating backups;
* stopping related services;
* copying content with `rsync`;
* restoring data during rollback;
* validating migration results.

### `core/fstab.py`

Responsible for:

* reading and interpreting `fstab`;
* detecting conflicts;
* commenting out old entries;
* adding new entries;
* generating a logical diff of changes.

### `core/snapper.py`

Responsible for:

* detecting Snapper availability;
* listing configurations;
* creating the `root` config;
* validating `/.snapshots`;
* enabling timers.

### `core/boot.py`

Responsible for:

* detecting GRUB or systemd-boot;
* regenerating GRUB;
* integrating `grub-btrfs` when available;
* handling snapshot integration for `systemd-boot`.

### `core/packages.py`

Responsible for:

* checking required binaries and packages;
* mapping dependencies by feature;
* installing dependencies with `apt` after confirmation.

### `core/profiles.py`

Responsible for:

* defining ready-made subvolume profiles;
* suggesting layouts compatible with Snapper;
* grouping subvolumes by use case.

### `core/state.py`

Responsible for:

* recording executed actions;
* persisting state between runs;
* storing backups and rollback metadata.

---

## Subvolume profiles

### Minimal Snapper

Includes:

* `/.snapshots`
* `/root`
* `/var/log`

### Desktop

Includes:

* the minimal profile;
* `/home` when it is on Btrfs or part of the same Btrfs filesystem;
* `/var/cache`
* `/var/tmp`

### Containers and Apps

Includes:

* `/var/lib/flatpak`
* `/var/lib/libvirt`
* `/var/lib/containers`
* `/var/lib/waydroid`

### Complete

Includes:

* all previous profiles;
* `/tmp` as an additional option.

---

## Operation flow

### 1. Audit

The app collects system information and presents:

* the current layout;
* existing subvolumes;
* `/home` mount and filesystem status;
* inconsistencies;
* missing dependencies;
* known risks.

### 2. Selection

The user chooses:

* a ready-made profile;
* individual subvolumes;
* Snapper integration;
* bootloader integration.

### 3. Planning

The application builds a plan with:

* packages to install;
* services to stop;
* subvolumes to create;
* directories to migrate;
* `fstab` entries to write;
* backups to generate.

### 4. Apply

Changes are applied with real-time logs.

### 5. Validation

After execution, the application verifies:

* created subvolumes;
* active mounts;
* `fstab` integrity;
* Snapper status;
* bootloader status, when applicable.

### 6. Rollback

If needed, the application allows the user to:

* restore previous directories;
* remove added mounts;
* revert `fstab` changes;
* delete created subvolumes;
* keep or delete backups.

---

## Safety

The project follows these principles:

* no critical change should occur without plan review;
* every write to `fstab` must generate a backup;
* every migration must generate a backup of the original directory;
* subvolume deletion must require strong confirmation;
* experimental integrations must be clearly marked;
* all actions must be logged.

---

## State and rollback

The application should persist a state file containing:

* execution timestamp;
* performed operations;
* created subvolumes;
* generated backups;
* lines added to or commented in `fstab`;
* reversible items.

Conceptual example:

```json
{
  "runs": [
    {
      "id": "2026-04-19T15:42:00",
      "actions": [
        {
          "target": "/var/lib/flatpak",
          "subvolume": "@var@lib@flatpak",
          "backup": "/var/lib/flatpak.old-pre-subvol.2026-04-19T15:42:00",
          "fstab_added": true,
          "status": "success"
        }
      ]
    }
  ]
}
```

---

## Dependencies

### Essential

* `python3`
* `btrfs-progs`
* `rsync`
* `util-linux`

### Functional

* `snapper`
* `grub` or equivalent boot tools
* `systemd-boot` when selected

### Python

* `textual`

Optional dependencies are only required when the corresponding feature is enabled.

---

## Requirements

* Linux system with a Btrfs root filesystem;
* administrator privileges;
* an environment compatible with `apt` for automatic package installation;
* an interactive terminal;
* access to `fstab` and mountpoints.

---

## Name

**DBLM — Btrfs Layout Manager**

---

## Target audience

This project is useful for:

* advanced Debian users with Btrfs;
* workstation administrators;
* desktop environments using Snapper;
* setups with Flatpak, containers, VMs, and Waydroid;
* people who want to reorganize an existing Btrfs system without reinstalling.

---

## Design principles

* clear interface;
* auditable operations;
* reversible changes;
* compatibility with real-world layouts;
* safety first;
* modular architecture.

---

## License

This project is licensed under the **Apache License 2.0**.
