from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Static

from core.system import command_exists, run_command, EnvironmentSnapshot, scan_environment


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _safe(value: str | None, fallback: str = "unknown") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text if text else fallback


class SnapperScreen(Screen[None]):
    """Snapper inspection screen for DBLM."""

    BINDINGS = [
        ("r", "refresh_snapper", "Refresh"),
    ]

    def __init__(self, state_file: str | Path = "data/state.json") -> None:
        super().__init__()
        self.state_file = Path(state_file)
        self.snapshot: EnvironmentSnapshot | None = None
        self.last_error: str | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="snapper-root"):
            yield Static("[bold]Snapper[/bold]", id="snapper-title")
            yield Static(
                "Inspect Snapper availability, basic configuration, and layout readiness.",
                id="snapper-subtitle",
            )

            with Horizontal(id="snapper-actions"):
                yield Button("Refresh", id="refresh-snapper", variant="primary")

            with Horizontal(id="snapper-grid"):
                with Vertical(id="snapper-left"):
                    yield Static("[bold]Snapper status[/bold]", classes="panel-title")
                    yield Static(id="snapper-status")

                    yield Static("[bold]Configurations[/bold]", classes="panel-title")
                    yield Static(id="snapper-configs")

                with Vertical(id="snapper-right"):
                    yield Static("[bold]Snapshot layout[/bold]", classes="panel-title")
                    yield Static(id="snapper-layout")

                    yield Static("[bold]Timers[/bold]", classes="panel-title")
                    yield Static(id="snapper-timers")

            yield Static("[bold]Notes[/bold]", classes="panel-title")
            yield Static(id="snapper-notes")

    def on_mount(self) -> None:
        self.refresh_snapper()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "refresh-snapper":
            self.refresh_snapper()

    def action_refresh_snapper(self) -> None:
        self.refresh_snapper()

    def refresh_snapper(self) -> None:
        try:
            self.snapshot = scan_environment()
            self.last_error = None
        except Exception as exc:  # pragma: no cover - defensive UI path
            self.snapshot = None
            self.last_error = str(exc)

        self._render()

    def _render(self) -> None:
        status_box = self.query_one("#snapper-status", Static)
        configs_box = self.query_one("#snapper-configs", Static)
        layout_box = self.query_one("#snapper-layout", Static)
        timers_box = self.query_one("#snapper-timers", Static)
        notes_box = self.query_one("#snapper-notes", Static)

        if self.snapshot is None:
            error = _safe(self.last_error)
            status_box.update(f"[bold]Snapper status[/bold]\n\nEnvironment scan failed.\n\nError: {error}")
            configs_box.update("No Snapper data available.")
            layout_box.update("No layout data available.")
            timers_box.update("No timer data available.")
            notes_box.update("Refresh the screen after fixing the environment issue.")
            return

        status_box.update(self._build_status_text())
        configs_box.update(self._build_configs_text())
        layout_box.update(self._build_layout_text())
        timers_box.update(self._build_timers_text())
        notes_box.update(self._build_notes_text())

    def _build_status_text(self) -> str:
        has_snapper = command_exists("snapper")
        version = self._snapper_version() if has_snapper else None

        return (
            "[bold]Snapper status[/bold]\n\n"
            f"snapper command available: {_yes_no(has_snapper)}\n"
            f"Version: {_safe(version, 'not available')}\n"
            f"Can inspect configs: {_yes_no(has_snapper)}"
        )

    def _build_configs_text(self) -> str:
        if not command_exists("snapper"):
            return (
                "[bold]Configurations[/bold]\n\n"
                "Snapper is not installed or not available in PATH."
            )

        configs = self._snapper_configs()
        if not configs:
            return (
                "[bold]Configurations[/bold]\n\n"
                "No Snapper configurations were detected."
            )

        return "[bold]Configurations[/bold]\n\n" + "\n".join(f"- {config}" for config in configs)

    def _build_layout_text(self) -> str:
        snapshot = self.snapshot
        assert snapshot is not None

        root = snapshot.root_fs
        home = snapshot.home_fs
        snapshots_path_exists = Path("/.snapshots").exists()

        return (
            "[bold]Snapshot layout[/bold]\n\n"
            f"Root is Btrfs: {_yes_no(root.is_btrfs)}\n"
            f"Root subvolume: {_safe(root.subvol)}\n"
            f"/.snapshots exists: {_yes_no(snapshots_path_exists)}\n"
            f"/home supports Btrfs subvolumes: {_yes_no(home.home_supports_subvolumes)}\n\n"
            "Expected common layout targets:\n"
            "- /.snapshots\n"
            "- /root\n"
            "- /var/log\n"
            "- /var/cache\n"
            "- /var/tmp"
        )

    def _build_timers_text(self) -> str:
        timeline = self._systemd_unit_state("snapper-timeline.timer")
        cleanup = self._systemd_unit_state("snapper-cleanup.timer")

        return (
            "[bold]Timers[/bold]\n\n"
            f"snapper-timeline.timer: {_safe(timeline)}\n"
            f"snapper-cleanup.timer: {_safe(cleanup)}"
        )

    def _build_notes_text(self) -> str:
        snapshot = self.snapshot
        assert snapshot is not None

        notes: list[str] = []

        if not command_exists("snapper"):
            notes.append("- Snapper is not installed yet.")

        if not Path("/.snapshots").exists():
            notes.append("- /.snapshots does not exist yet.")

        if snapshot.root_fs.fstype != "btrfs":
            notes.append("- Root is not Btrfs, so Snapper integration should not proceed.")

        if snapshot.home_fs.is_separate_btrfs:
            notes.append("- /home is a separate Btrfs filesystem and should be treated as its own scope.")

        if not notes:
            notes.append("- Snapper prerequisites look reasonable for the next implementation step.")

        return "\n".join(notes)

    def _snapper_version(self) -> str | None:
        result = run_command(["snapper", "--version"], check=False)
        if not result.ok:
            return None
        first_line = result.stdout.splitlines()[0] if result.stdout else ""
        return first_line.strip() or None

    def _snapper_configs(self) -> list[str]:
        result = run_command(["snapper", "list-configs"], check=False)
        if not result.ok or not result.stdout:
            return []

        configs: list[str] = []
        lines = result.stdout.splitlines()

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.lower().startswith("config"):
                continue
            configs.append(stripped)

        return configs

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
