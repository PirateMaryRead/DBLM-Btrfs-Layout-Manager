from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Static

from core.state import StateManager
from core.system import EnvironmentSnapshot, scan_environment


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _safe(value: str | None, fallback: str = "unknown") -> str:
    if value is None:
        return fallback
    value = str(value).strip()
    return value if value else fallback


class InfoCard(Static):
    """Simple bordered block used by the dashboard."""

    DEFAULT_CLASSES = "dashboard-card"


class DashboardScreen(Screen[None]):
    """Dashboard screen for DBLM."""

    BINDINGS = [
        ("r", "refresh_dashboard", "Refresh"),
    ]

    def __init__(self, state_file: str | Path = "data/state.json") -> None:
        super().__init__()
        self.state_manager = StateManager(state_file)
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
            self.snapshot = scan_environment()
            self.last_error = None
        except Exception as exc:  # pragma: no cover - defensive UI path
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
                f"Unable to scan environment.\n\nError: {_safe(self.last_error)}"
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
            f"Host: {_safe(snapshot.hostname)}\n"
            f"Distro: {_safe(snapshot.distro)}\n"
            f"Kernel: {_safe(snapshot.kernel)}\n"
            f"Running as root: {_yes_no(snapshot.is_root)}\n\n"
            f"Root mount: {_safe(root.mountpoint)}\n"
            f"Root source: {_safe(root.source)}\n"
            f"Root fstype: {_safe(root.fstype)}\n"
            f"Root UUID: {_safe(root.uuid)}\n"
            f"Root subvolume: {_safe(root.subvol)}\n"
            f"Root subvolid: {_safe(root.subvolid)}\n\n"
            f"Required dependencies OK: {_yes_no(deps.required_ok)}\n"
            f"Missing required: {', '.join(deps.missing_required) if deps.missing_required else 'none'}"
        )

    def _build_home_text(self, snapshot: EnvironmentSnapshot) -> str:
        home = snapshot.home_fs

        if not home.exists:
            return "[bold]Home[/bold]\n\n/home was not found on this system."

        return (
            "[bold]Home[/bold]\n\n"
            f"Home source: {_safe(home.source)}\n"
            f"Home fstype: {_safe(home.fstype)}\n"
            f"Home UUID: {_safe(home.uuid)}\n"
            f"Separate mount: {_yes_no(home.separately_mounted)}\n"
            f"Btrfs: {_yes_no(home.is_btrfs)}\n"
            f"Same device as /: {_yes_no(bool(home.same_device_as_root))}\n"
            f"Supports home subvolumes: {_yes_no(home.home_supports_subvolumes)}\n\n"
            f"Summary: {home.display_name}"
        )

    def _build_boot_text(self, snapshot: EnvironmentSnapshot) -> str:
        boot = snapshot.bootloader

        return (
            "[bold]Boot[/bold]\n\n"
            f"Detected bootloader: {_safe(boot.detected)}\n"
            f"UEFI: {_yes_no(boot.is_uefi)}\n"
            f"EFI mountpoint: {_safe(boot.efi_mountpoint)}\n"
            f"GRUB available: {_yes_no(boot.has_grub)}\n"
            f"grub-mkconfig available: {_yes_no(boot.has_grub_mkconfig)}\n"
            f"bootctl available: {_yes_no(boot.has_bootctl)}\n"
            f"systemd-boot detected: {_yes_no(boot.has_systemd_boot)}\n"
            f"grub-btrfsd available: {_yes_no(boot.has_grub_btrfsd)}"
        )

    def _build_state_text(self, summary: dict[str, Any]) -> str:
        return (
            "[bold]State[/bold]\n\n"
            f"Runs recorded: {summary.get('runs_total', 0)}\n"
            f"Backups recorded: {summary.get('backups_total', 0)}\n"
            f"Available backups: {summary.get('backups_available', 0)}\n"
            f"Restorable backups: {summary.get('backups_restorable', 0)}\n"
            f"Deleted backups: {summary.get('backups_deleted', 0)}\n"
            f"Latest run: {_safe(summary.get('latest_run_id'))}\n\n"
            "Backup actions supported:\n"
            "- restore recorded backups\n"
            "- delete recorded backups"
        )

    def _build_warnings_text(self, snapshot: EnvironmentSnapshot) -> str:
        if not snapshot.warnings:
            return "[bold]Warnings[/bold]\n\nNo warnings detected."

        lines = "\n".join(f"- {warning}" for warning in snapshot.warnings)
        return f"[bold]Warnings[/bold]\n\n{lines}"
