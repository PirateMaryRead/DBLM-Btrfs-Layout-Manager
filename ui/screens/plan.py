from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Static

from core.profiles import filter_targets_for_home_support, list_targets
from core.system import EnvironmentSnapshot
from ui.common import DBLMSectionScreen, safe_text, yes_no


class PlanScreen(DBLMSectionScreen):
    BINDINGS = [("r", "refresh_plan", "Refresh")]

    def __init__(self, state_file: str | Path = "data/state.json") -> None:
        super().__init__(state_file=state_file)
        self.snapshot: EnvironmentSnapshot | None = None
        self.last_error: str | None = None

    def compose_body(self) -> ComposeResult:
        with Vertical(id="plan-root"):
            yield Static("[bold]Plan[/bold]", id="plan-title")
            yield Static(
                "Review the current environment and the operations DBLM is expected to manage.",
                id="plan-subtitle",
            )

            with Horizontal(id="plan-actions"):
                yield Button("Refresh", id="refresh-plan", variant="primary")

            with Horizontal(id="plan-grid"):
                with Vertical(id="plan-left"):
                    yield Static("[bold]Execution overview[/bold]", classes="panel-title")
                    yield Static(id="plan-overview")

                    yield Static("[bold]Filesystem scope[/bold]", classes="panel-title")
                    yield Static(id="plan-filesystems")

                with Vertical(id="plan-right"):
                    yield Static("[bold]Available targets[/bold]", classes="panel-title")
                    yield Static(id="plan-targets")

                    yield Static("[bold]Backups and restore[/bold]", classes="panel-title")
                    yield Static(id="plan-backups")

            yield Static("[bold]Notes[/bold]", classes="panel-title")
            yield Static(id="plan-notes")

    def on_mount(self) -> None:
        self.refresh_plan()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "refresh-plan":
            self.refresh_plan()

    def action_refresh_plan(self) -> None:
        self.refresh_plan()

    def refresh_plan(self) -> None:
        try:
            self.snapshot = self.get_environment(force=True)
            self.last_error = None
        except Exception as exc:  # pragma: no cover
            self.snapshot = None
            self.last_error = str(exc)

        self._render()

    def _render(self) -> None:
        overview = self.query_one("#plan-overview", Static)
        filesystems = self.query_one("#plan-filesystems", Static)
        targets = self.query_one("#plan-targets", Static)
        backups = self.query_one("#plan-backups", Static)
        notes = self.query_one("#plan-notes", Static)

        if self.snapshot is None:
            error_text = safe_text(self.last_error)
            overview.update(f"[bold]Plan unavailable[/bold]\n\nEnvironment scan failed.\n\nError: {error_text}")
            filesystems.update("No filesystem data available.")
            targets.update("No target data available.")
            backups.update("No backup data available.")
            notes.update("Refresh the screen after fixing the environment issue.")
            return

        summary = self.state_manager.summarize()
        available_targets = self._available_targets()

        overview.update(self._build_overview_text(summary, available_targets))
        filesystems.update(self._build_filesystem_text())
        targets.update(self._build_targets_text(available_targets))
        backups.update(self._build_backups_text(summary))
        notes.update(self._build_notes_text())

    def _available_targets(self):
        include_home = bool(self.snapshot and self.snapshot.home_fs.home_supports_subvolumes)
        return filter_targets_for_home_support(
            list_targets(include_home=include_home),
            home_is_btrfs=include_home,
        )

    def _build_overview_text(self, summary: dict[str, object], available_targets: list) -> str:
        snapshot = self.snapshot
        assert snapshot is not None
        deps = snapshot.dependencies

        return (
            "[bold]Execution overview[/bold]\n\n"
            f"Host: {safe_text(snapshot.hostname)}\n"
            f"Distro: {safe_text(snapshot.distro)}\n"
            f"Root filesystem type: {safe_text(snapshot.root_fs.fstype)}\n"
            f"Root subvolume: {safe_text(snapshot.root_fs.subvol)}\n\n"
            f"Required dependencies OK: {yes_no(deps.required_ok)}\n"
            f"Missing required commands: {', '.join(deps.missing_required) if deps.missing_required else 'none'}\n"
            f"Warnings detected: {len(snapshot.warnings)}\n"
            f"Known manageable targets: {len(available_targets)}\n\n"
            f"Recorded runs: {summary.get('runs_total', 0)}\n"
            f"Recorded backups: {summary.get('backups_total', 0)}"
        )

    def _build_filesystem_text(self) -> str:
        snapshot = self.snapshot
        assert snapshot is not None
        root = snapshot.root_fs
        home = snapshot.home_fs

        return (
            "[bold]Filesystem scope[/bold]\n\n"
            f"System root source: {safe_text(root.source)}\n"
            f"System root UUID: {safe_text(root.uuid)}\n"
            f"System root Btrfs: {yes_no(root.is_btrfs)}\n\n"
            f"/home exists: {yes_no(home.exists)}\n"
            f"/home source: {safe_text(home.source)}\n"
            f"/home filesystem type: {safe_text(home.fstype)}\n"
            f"/home separate mount: {yes_no(home.separately_mounted)}\n"
            f"/home Btrfs: {yes_no(home.is_btrfs)}\n"
            f"/home same device as /: {yes_no(bool(home.same_device_as_root))}\n"
            f"/home subvolume support: {yes_no(home.home_supports_subvolumes)}\n\n"
            f"Home summary: {home.display_name}"
        )

    def _build_targets_text(self, available_targets: list) -> str:
        if not available_targets:
            return "[bold]Available targets[/bold]\n\nNo manageable targets detected."

        lines = [
            f"- {target.path} [{'home' if target.scope == 'home' else 'system'}] → {target.suggested_name(flat_layout=True)}"
            for target in available_targets
        ]
        return "[bold]Available targets[/bold]\n\n" + "\n".join(lines)

    def _build_backups_text(self, summary: dict[str, object]) -> str:
        return (
            "[bold]Backups and restore[/bold]\n\n"
            f"Available backups: {summary.get('backups_available', 0)}\n"
            f"Restorable backups: {summary.get('backups_restorable', 0)}\n"
            f"Deleted backups: {summary.get('backups_deleted', 0)}\n\n"
            "Supported operations:\n"
            "- register backup metadata\n"
            "- restore a recorded backup\n"
            "- delete a recorded backup\n"
            "- track rollback-related state"
        )

    def _build_notes_text(self) -> str:
        snapshot = self.snapshot
        assert snapshot is not None

        notes: list[str] = []
        if snapshot.root_fs.fstype != "btrfs":
            notes.append("- Root is not Btrfs. DBLM management should not proceed.")
        if snapshot.home_fs.exists and snapshot.home_fs.separately_mounted and not snapshot.home_fs.is_btrfs:
            notes.append("- /home is separate and not Btrfs, so home subvolume management is disabled.")
        if snapshot.home_fs.is_separate_btrfs:
            notes.append("- /home is a separate Btrfs filesystem and should be managed as its own scope.")
        if not snapshot.dependencies.required_ok:
            notes.append("- Install missing required commands before applying any changes.")
        if not notes:
            notes.append("- Environment looks suitable for the next implementation steps.")
        return "\n".join(notes)
