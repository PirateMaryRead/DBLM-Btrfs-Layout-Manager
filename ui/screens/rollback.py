from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Static

from core.system import EnvironmentSnapshot
from ui.common import DBLMScreen, safe_text


class RollbackScreen(DBLMScreen):
    BINDINGS = [("r", "refresh_rollback", "Refresh")]

    def __init__(self, state_file: str | Path = "data/state.json") -> None:
        super().__init__(state_file=state_file)
        self.snapshot: EnvironmentSnapshot | None = None
        self.last_error: str | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="rollback-root"):
            yield Static("[bold]Revert[/bold]", id="rollback-title")
            yield Static(
                "Inspect revertable actions, recorded runs, and backup-based recovery options.",
                id="rollback-subtitle",
            )

            with Horizontal(id="rollback-actions"):
                yield Button("Refresh", id="refresh-rollback", variant="primary")

            with Horizontal(id="rollback-grid"):
                with Vertical(id="rollback-left"):
                    yield Static("[bold]Latest run[/bold]", classes="panel-title")
                    yield Static(id="rollback-run")

                    yield Static("[bold]Revertable actions[/bold]", classes="panel-title")
                    yield Static(id="rollback-actions-list")

                with Vertical(id="rollback-right"):
                    yield Static("[bold]Backup recovery[/bold]", classes="panel-title")
                    yield Static(id="rollback-backups")

                    yield Static("[bold]Subvolume removal[/bold]", classes="panel-title")
                    yield Static(id="rollback-subvolumes")

            yield Static("[bold]Notes[/bold]", classes="panel-title")
            yield Static(id="rollback-notes")

    def on_mount(self) -> None:
        self.refresh_rollback()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "refresh-rollback":
            self.refresh_rollback()

    def action_refresh_rollback(self) -> None:
        self.refresh_rollback()

    def refresh_rollback(self) -> None:
        try:
            self.snapshot = self.get_environment(force=True)
            self.last_error = None
        except Exception as exc:  # pragma: no cover
            self.snapshot = None
            self.last_error = str(exc)

        self._render()

    def _render(self) -> None:
        run_box = self.query_one("#rollback-run", Static)
        actions_box = self.query_one("#rollback-actions-list", Static)
        backups_box = self.query_one("#rollback-backups", Static)
        subvolumes_box = self.query_one("#rollback-subvolumes", Static)
        notes_box = self.query_one("#rollback-notes", Static)

        if self.snapshot is None:
            error = safe_text(self.last_error)
            run_box.update(f"[bold]Latest run[/bold]\n\nEnvironment scan failed.\n\nError: {error}")
            actions_box.update("No rollback action data available.")
            backups_box.update("No backup recovery data available.")
            subvolumes_box.update("No subvolume data available.")
            notes_box.update("Refresh the screen after fixing the environment issue.")
            return

        latest_run = self.state_manager.get_latest_run()
        restorable_backups = self.state_manager.list_restorable_backups()

        run_box.update(self._build_run_text(latest_run))
        actions_box.update(self._build_actions_text(latest_run))
        backups_box.update(self._build_backups_text(restorable_backups))
        subvolumes_box.update(self._build_subvolumes_text(latest_run))
        notes_box.update(self._build_notes_text(latest_run, restorable_backups))

    def _build_run_text(self, latest_run) -> str:
        if latest_run is None:
            return "[bold]Latest run[/bold]\n\nNo recorded run exists yet."

        return (
            "[bold]Latest run[/bold]\n\n"
            f"Run id: {latest_run.run_id}\n"
            f"Created at: {latest_run.created_at}\n"
            f"Status: {latest_run.status}\n"
            f"Recorded actions: {len(latest_run.actions)}\n"
            f"Warnings: {len(latest_run.warnings)}\n"
            f"Notes: {safe_text(latest_run.notes, 'none')}"
        )

    def _build_actions_text(self, latest_run) -> str:
        if latest_run is None or not latest_run.actions:
            return (
                "[bold]Revertable actions[/bold]\n\n"
                "No actions are currently recorded for rollback."
            )

        lines = [
            f"- {action.target} -> {action.subvolume or 'n/a'} "
            f"[status={action.status}, backup={'yes' if action.backup_id else 'no'}]"
            for action in latest_run.actions
        ]
        return "[bold]Revertable actions[/bold]\n\n" + "\n".join(lines)

    def _build_backups_text(self, restorable_backups) -> str:
        if not restorable_backups:
            return (
                "[bold]Backup recovery[/bold]\n\n"
                "No restorable backups are currently available."
            )

        lines = [
            f"- {backup.backup_id}: {backup.original_path} <- {backup.backup_path}"
            for backup in restorable_backups[:10]
        ]
        return (
            "[bold]Backup recovery[/bold]\n\n"
            f"Restorable backups: {len(restorable_backups)}\n\n"
            + "\n".join(lines)
            + "\n\nSupported actions:\n"
            "- restore backup to original path\n"
            "- overwrite an existing target during restore\n"
            "- keep backup after restore or delete it later"
        )

    def _build_subvolumes_text(self, latest_run) -> str:
        if latest_run is None or not latest_run.actions:
            return (
                "[bold]Subvolume removal[/bold]\n\n"
                "No created subvolumes are currently recorded."
            )

        lines = [
            f"- target={action.target} subvolume={action.subvolume} scope={action.filesystem_scope}"
            for action in latest_run.actions
            if action.subvolume
        ]
        if not lines:
            return (
                "[bold]Subvolume removal[/bold]\n\n"
                "No removable subvolumes were recorded in the latest run."
            )

        return (
            "[bold]Subvolume removal[/bold]\n\n"
            + "\n".join(lines)
            + "\n\nRollback path:\n"
            "- unmount target if mounted\n"
            "- restore original backup if available\n"
            "- optionally delete the created subvolume"
        )

    def _build_notes_text(self, latest_run, restorable_backups) -> str:
        notes: list[str] = []

        if latest_run is None:
            notes.append("- No run has been recorded yet, so there is nothing to revert.")
        else:
            if latest_run.status == "success":
                notes.append("- Successful runs can still be reverted if backups and metadata exist.")
            if latest_run.status == "failed":
                notes.append("- Failed runs should be reviewed carefully before retrying or reverting.")

        if not restorable_backups:
            notes.append("- No backup is currently available for restore operations.")
        else:
            notes.append("- Backup restore is available for recorded items.")

        notes.append("- Backup deletion is handled separately in the Backups screen.")
        return "\n".join(notes)
