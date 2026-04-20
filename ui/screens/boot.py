from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Static

from core.system import EnvironmentSnapshot, command_exists, run_command
from ui.common import DBLMSectionScreen, safe_text, yes_no


class BootScreen(DBLMSectionScreen):
    """Bootloader inspection screen for DBLM."""

    BINDINGS = [("r", "refresh_boot", "Refresh")]

    def __init__(self, state_file: str | Path = "data/state.json") -> None:
        super().__init__(state_file=state_file)
        self.snapshot: EnvironmentSnapshot | None = None
        self.last_error: str | None = None

    def compose_body(self) -> ComposeResult:
        with Vertical(id="boot-root"):
            yield Static("[bold]Boot[/bold]", id="boot-title")
            yield Static(
                "Inspect bootloader detection and available integration points.",
                id="boot-subtitle",
            )

            with Horizontal(id="boot-actions"):
                yield Button("Refresh", id="refresh-boot", variant="primary")

            with Horizontal(id="boot-grid"):
                with Vertical(id="boot-left"):
                    yield Static("[bold]Detected boot environment[/bold]", classes="panel-title")
                    yield Static(id="boot-status")

                    yield Static("[bold]GRUB integration[/bold]", classes="panel-title")
                    yield Static(id="boot-grub")

                with Vertical(id="boot-right"):
                    yield Static("[bold]systemd-boot integration[/bold]", classes="panel-title")
                    yield Static(id="boot-systemd")

                    yield Static("[bold]Snapshot boot integration[/bold]", classes="panel-title")
                    yield Static(id="boot-snapshots")

            yield Static("[bold]Notes[/bold]", classes="panel-title")
            yield Static(id="boot-notes")

    def on_mount(self) -> None:
        self.refresh_boot()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "refresh-boot":
            self.refresh_boot()

    def action_refresh_boot(self) -> None:
        self.refresh_boot()

    def refresh_boot(self) -> None:
        try:
            self.snapshot = self.get_environment(force=True)
            self.last_error = None
        except Exception as exc:  # pragma: no cover
            self.snapshot = None
            self.last_error = str(exc)

        self._render()

    def _render(self) -> None:
        status_box = self.query_one("#boot-status", Static)
        grub_box = self.query_one("#boot-grub", Static)
        systemd_box = self.query_one("#boot-systemd", Static)
        snapshots_box = self.query_one("#boot-snapshots", Static)
        notes_box = self.query_one("#boot-notes", Static)

        if self.snapshot is None:
            error = safe_text(self.last_error)
            status_box.update(f"[bold]Boot[/bold]\n\nEnvironment scan failed.\n\nError: {error}")
            grub_box.update("No GRUB data available.")
            systemd_box.update("No systemd-boot data available.")
            snapshots_box.update("No snapshot integration data available.")
            notes_box.update("Refresh the screen after fixing the environment issue.")
            return

        status_box.update(self._build_status_text())
        grub_box.update(self._build_grub_text())
        systemd_box.update(self._build_systemd_boot_text())
        snapshots_box.update(self._build_snapshot_text())
        notes_box.update(self._build_notes_text())

    def _build_status_text(self) -> str:
        snapshot = self.snapshot
        assert snapshot is not None

        boot = snapshot.bootloader

        return (
            "[bold]Detected boot environment[/bold]\n\n"
            f"Detected bootloader: {safe_text(boot.detected)}\n"
            f"UEFI: {yes_no(boot.is_uefi)}\n"
            f"EFI mountpoint: {safe_text(boot.efi_mountpoint)}\n"
            f"GRUB available: {yes_no(boot.has_grub)}\n"
            f"grub-mkconfig available: {yes_no(boot.has_grub_mkconfig)}\n"
            f"bootctl available: {yes_no(boot.has_bootctl)}\n"
            f"systemd-boot detected: {yes_no(boot.has_systemd_boot)}\n"
            f"grub-btrfsd available: {yes_no(boot.has_grub_btrfsd)}"
        )

    def _build_grub_text(self) -> str:
        snapshot = self.snapshot
        assert snapshot is not None
        boot = snapshot.bootloader

        grub_install = _command_version("grub-install", "--version")
        grub_mkconfig = _command_version("grub-mkconfig", "--version")
        grub_btrfsd = _command_version("grub-btrfsd", "--version")

        return (
            "[bold]GRUB integration[/bold]\n\n"
            f"GRUB tooling available: {yes_no(boot.has_grub or boot.has_grub_mkconfig)}\n"
            f"grub-install: {safe_text(grub_install, 'not available')}\n"
            f"grub-mkconfig: {safe_text(grub_mkconfig, 'not available')}\n"
            f"grub-btrfsd: {safe_text(grub_btrfsd, 'not available')}\n\n"
            "Planned DBLM support:\n"
            "- detect current GRUB environment\n"
            "- regenerate boot configuration\n"
            "- integrate grub-btrfs when available"
        )

    def _build_systemd_boot_text(self) -> str:
        snapshot = self.snapshot
        assert snapshot is not None
        boot = snapshot.bootloader

        bootctl_version = _command_version("bootctl", "--version")
        is_installed = self._bootctl_is_installed()

        return (
            "[bold]systemd-boot integration[/bold]\n\n"
            f"bootctl available: {yes_no(boot.has_bootctl)}\n"
            f"systemd-boot detected: {yes_no(boot.has_systemd_boot)}\n"
            f"bootctl version: {safe_text(bootctl_version, 'not available')}\n"
            f"bootctl is-installed: {safe_text(is_installed, 'unknown')}\n"
            f"EFI mountpoint: {safe_text(boot.efi_mountpoint)}\n\n"
            "Planned DBLM support:\n"
            "- detect loader presence\n"
            "- validate EFI environment\n"
            "- prepare boot entry integration"
        )

    def _build_snapshot_text(self) -> str:
        snapshots_exists = Path("/.snapshots").exists()
        grub_btrfs_path = self._systemd_unit_state("grub-btrfs.path")
        grub_btrfs_service = self._systemd_unit_state("grub-btrfs.service")

        return (
            "[bold]Snapshot boot integration[/bold]\n\n"
            f"/.snapshots exists: {yes_no(snapshots_exists)}\n"
            f"grub-btrfs.path: {safe_text(grub_btrfs_path)}\n"
            f"grub-btrfs.service: {safe_text(grub_btrfs_service)}\n\n"
            "Current scope:\n"
            "- detect snapshot-related tooling\n"
            "- inspect boot integration readiness\n"
            "- prepare future boot entry generation"
        )

    def _build_notes_text(self) -> str:
        snapshot = self.snapshot
        assert snapshot is not None

        boot = snapshot.bootloader
        notes: list[str] = []

        if boot.detected == "unknown":
            notes.append("- Bootloader could not be identified confidently.")
        if boot.detected == "grub" and not boot.has_grub_mkconfig:
            notes.append("- GRUB appears available, but grub-mkconfig is missing.")
        if boot.is_uefi and not boot.efi_mountpoint:
            notes.append("- UEFI was detected, but no EFI mountpoint was identified at /boot/efi.")
        if Path("/.snapshots").exists() and not boot.has_grub_btrfsd:
            notes.append("- Snapshots exist, but grub-btrfs tooling was not detected.")
        if boot.has_bootctl and not boot.is_uefi:
            notes.append("- bootctl is present, but the system does not appear to be booted in UEFI mode.")
        if not notes:
            notes.append("- Boot environment looks suitable for the next implementation step.")

        return "\n".join(notes)

    def _bootctl_is_installed(self) -> str | None:
        if not command_exists("bootctl"):
            return None

        result = run_command(["bootctl", "is-installed"], check=False)
        if result.ok:
            return "yes"
        if result.returncode != 0:
            stderr = result.stderr.strip()
            stdout = result.stdout.strip()
            if stdout:
                return stdout
            if stderr:
                return stderr
            return "no"
        return None

    def _systemd_unit_state(self, unit_name: str) -> str | None:
        if not command_exists("systemctl"):
            return "systemctl unavailable"

        result = run_command(["systemctl", "is-enabled", unit_name], check=False)
        if result.ok and result.stdout:
            return result.stdout.strip()

        active = run_command(["systemctl", "is-active", unit_name], check=False)
        if active.ok and active.stdout:
            return active.stdout.strip()

        if result.stderr:
            return result.stderr.strip()
        return "not found"


def _command_version(binary: str, flag: str = "--version") -> str | None:
    if not command_exists(binary):
        return None

    result = run_command([binary, flag], check=False)
    if not result.ok and not result.stdout:
        return None

    first_line = result.stdout.splitlines()[0] if result.stdout else ""
    return first_line.strip() or None
