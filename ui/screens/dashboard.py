from __future__ import annotations

from pathlib import Path
from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Static

from core.system import EnvironmentSnapshot
from ui.common import DBLMScreen, safe_text, yes_no


class InfoCard(Static):
    """Simple bordered block used by the dashboard."""

    DEFAULT_CLASSES = "dashboard-card"


class DashboardScreen(DBLMScreen):
    """Dashboard screen for DBLM."""

    BINDINGS = [("r", "refresh_dashboard", "Refresh")]

    def __init__(self, state_file: str | Path = "data/state.json") -> None:
        super().__init__(state_file=state_file)
        self.snapshot: EnvironmentSnapshot | None = None
        self.last_error: str | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="dashboard-root"):
            yield Static("[bold]DBLM — Btrfs Layout Manager[/bold]", id="dashboard-title")
            yield Static(
                "Audit the current system, inspect Btrfs layout details, and review pending state.",
                id="dashboard-subtitle",
            )

            with Horizontal(id="dashboard-actions"):
                yield Button("Refresh", id="refresh-dashboard", variant="primary")

            with Horizontal(id="dashboard-grid"):
                yield InfoCard(id="card-system")
                yield InfoCard(id="card-home")
                yield InfoCard(id="card-boot")
                yield InfoCard(id="card-state")

            yield InfoCard(id="card-warnings")

    def on_mount(self) -> None:
        self.refresh_dashboard()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "refresh-dashboard":
            self.refresh_dashboard()

    def action_refresh_dashboard(self) -> None:
        self.refresh_dashboard()

    def refresh_dashboard(self) -> None:
        try:
            self.snapshot = self.get_environment(force=True)
            self.last_error = None
        except Exception as exc:  # pragma: no cover
            self.snapshot = None
            self.last_error = str(exc)

        self._render_cards()

    def _render_cards(self) -> None:
        system_card = self.query_one("#card-system", InfoCard)
        home_card = self.query_one("#card-home", InfoCard)
        boot_card = self.query_one("#card-boot", InfoCard)
        state_card = self.query_one("#card-state", InfoCard)
        warnings_card = self.query_one("#card-warnings", InfoCard)

        if self.snapshot is None:
            system_card.update(
                "[bold]System[/bold]\n\n"
                f"Unable to scan environment.\n\nError: {safe_text(self.last_error)}"
            )
            home_card.update("[bold]Home[/bold]\n\nNo data available.")
            boot_card.update("[bold]Boot[/bold]\n\nNo data available.")
            state_card.update("[bold]State[/bold]\n\nNo data available.")
            warnings_card.update("[bold]Warnings[/bold]\n\nEnvironment scan failed.")
            return

        summary = self.state_manager.summarize()
        system_card.update(self._build_system_text(self.snapshot))
        home_card.update(self._build_home_text(self.snapshot))
        boot_card.update(self._build_boot_text(self.snapshot))
        state_card.update(self._build_state_text(summary))
        warnings_card.update(self._build_warnings_text(self.snapshot))

    def _build_system_text(self, snapshot: EnvironmentSnapshot) -> str:
        root = snapshot.root_fs
        deps = snapshot.dependencies

        return (
            "[bold]System[/bold]\n\n"
            f"Host: {safe_text(snapshot.hostname)}\n"
            f"Distro: {safe_text(snapshot.distro)}\n"
            f"Kernel: {safe_text(snapshot.kernel)}\n"
            f"Running as root: {yes_no(snapshot.is_root)}\n\n"
            f"Root mount: {safe_text(root.mountpoint)}\n"
            f"Root source: {safe_text(root.source)}\n"
            f"Root fstype: {safe_text(root.fstype)}\n"
            f"Root UUID: {safe_text(root.uuid)}\n"
            f"Root subvolume: {safe_text(root.subvol)}\n"
            f"Root subvolid: {safe_text(root.subvolid)}\n\n"
            f"Required dependencies OK: {yes_no(deps.required_ok)}\n"
            f"Missing required: {', '.join(deps.missing_required) if deps.missing_required else 'none'}"
        )

    def _build_home_text(self, snapshot: EnvironmentSnapshot) -> str:
        home = snapshot.home_fs

        if not home.exists:
            return "[bold]Home[/bold]\n\n/home was not found on this system."

        return (
            "[bold]Home[/bold]\n\n"
            f"Home source: {safe_text(home.source)}\n"
            f"Home fstype: {safe_text(home.fstype)}\n"
            f"Home UUID: {safe_text(home.uuid)}\n"
            f"Separate mount: {yes_no(home.separately_mounted)}\n"
            f"Btrfs: {yes_no(home.is_btrfs)}\n"
            f"Same device as /: {yes_no(bool(home.same_device_as_root))}\n"
            f"Supports home subvolumes: {yes_no(home.home_supports_subvolumes)}\n\n"
            f"Summary: {home.display_name}"
        )

    def _build_boot_text(self, snapshot: EnvironmentSnapshot) -> str:
        boot = snapshot.bootloader

        return (
            "[bold]Boot[/bold]\n\n"
            f"Detected bootloader: {safe_text(boot.detected)}\n"
            f"UEFI: {yes_no(boot.is_uefi)}\n"
            f"EFI mountpoint: {safe_text(boot.efi_mountpoint)}\n"
            f"GRUB available: {yes_no(boot.has_grub)}\n"
            f"grub-mkconfig available: {yes_no(boot.has_grub_mkconfig)}\n"
            f"bootctl available: {yes_no(boot.has_bootctl)}\n"
            f"systemd-boot detected: {yes_no(boot.has_systemd_boot)}\n"
            f"grub-btrfsd available: {yes_no(boot.has_grub_btrfsd)}"
        )

    def _build_state_text(self, summary: dict[str, Any]) -> str:
        return (
            "[bold]State[/bold]\n\n"
            f"Runs recorded: {summary.get('runs_total', 0)}\n"
            f"Backups recorded: {summary.get('backups_total', 0)}\n"
            f"Available backups: {summary.get('backups_available', 0)}\n"
            f"Restorable backups: {summary.get('backups_restorable', 0)}\n"
            f"Deleted backups: {summary.get('backups_deleted', 0)}\n"
            f"Latest run: {safe_text(summary.get('latest_run_id'))}\n\n"
            "Backup actions supported:\n"
            "- restore recorded backups\n"
            "- delete recorded backups"
        )

    def _build_warnings_text(self, snapshot: EnvironmentSnapshot) -> str:
        if not snapshot.warnings:
            return "[bold]Warnings[/bold]\n\nNo warnings detected."

        lines = "\n".join(f"- {warning}" for warning in snapshot.warnings)
        return f"[bold]Warnings[/bold]\n\n{lines}"
