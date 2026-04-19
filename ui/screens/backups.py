from __future__ import annotations

from pathlib import Path

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
    text = str(value).strip()
    return text if text else fallback


class BackupsScreen(Screen[None]):
    """Backup inspection screen for DBLM."""

    BINDINGS = [
        ("r", "refresh_backups", "Refresh"),
    ]

    def __init__(self, state_file: str | Path = "data/state.json") -> None:
        super().__init__()
        self.state_manager = StateManager(state_file)
        self.snapshot: EnvironmentSnapshot | None = None
        self.last_error: str | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="backups-root"):
            yield Static("[bold]Backups[/bold]", id="backups-title")
            yield Static(
                "Inspect recorded backups and available restore and delete operations.",
                id="backups-subtitle",
            )

            with Horizontal(id="backups-actions"):
                yield Button("Refresh", id="refresh-backups", variant="primary")

            with Horizontal(id="backups-grid"):
                with Vertical(id="backups-left"):
                    yield Static("[bold]Backup summary[/bold]", classes="panel-title")
                    yield Static(id="backups-summary")

                    yield Static("[bold]Available backups[/bold]", classes="panel-title")
                    yield Static(id="backups-available")

                with Vertical(id="backups-right"):
                    yield Static("[bold]Restorable backups[/bold]", classes="panel-title")
                    yield Static(id="backups-restorable")

                    yield Static("[bold]Deleted backups[/bold]", classes="panel-title")
                    yield Static(id="backups-deleted")

            yield Static("[bold]Notes[/bold]", classes="panel-title")
            yield Static(id="backups-notes")

    def on_mount(self) -> None:
        self.refresh_backups()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "refresh-backups":
            self.refresh_backups()

    def action_refresh_backups(self) -> None:
        self.refresh_backups()

    def refresh_backups(self) -> None:
        try:
            self.snapshot = scan_environment()
            self.last_error = None
        except Exception as exc:  # pragma: no cover - defensive UI path
            self.snapshot = None
            self.last_error = str(exc)

        self._render()

    def _render(self) -> None:
        summary_box = self.query_one("#backups-summary", Static)
        available_box = self.query_one("#backups-available", Static)
        restorable_box = self.query_one("#backups-restorable", Static)
        deleted_box = self.query_one("#backups-deleted", Static)
        notes_box = self.query_one("#backups-notes", Static)

        if self.snapshot is None:
            error = _safe(self.last_error)
            summary_box.update(f"[bold]Backup summary[/bold]\n\nEnvironment scan failed.\n\nError: {error}")
            available_box.update("No backup data available.")
            restorable_box.update("No restore data available.")
            deleted_box.update("No deleted backup data available.")
            notes_box.update("Refresh the screen after fixing the environment issue.")
            return

        summary = self.state_manager.summarize()
        available = self.state_manager.list_backups(include_deleted=False)
        all_backups = self.state_manager.list_backups(include_deleted=True)
        deleted = [item for item in all_backups if item.deleted]
        restorable = self.state_manager.list_restorable_backups()

        summary_box.update(self._build_summary_text(summary))
        available_box.update(self._build_available_text(available))
        restorable_box.update(self._build_restorable_text(restorable))
        deleted_box.update(self._build_deleted_text(deleted))
        notes_box.update(self._build_notes_text(available, restorable, deleted))

    def _build_summary_text(self, summary: dict[str, object]) -> str:
        return (
            "[bold]Backup summary[/bold]\n\n"
            f"Backups total: {summary.get('backups_total', 0)}\n"
            f"Available backups: {summary.get('backups_available', 0)}\n"
            f"Restorable backups: {summary.get('backups_restorable', 0)}\n"
            f"Deleted backups: {summary.get('backups_deleted', 0)}\n"
            f"Latest run: {_safe(summary.get('latest_run_id'))}\n\n"
            "Supported operations:\n"
            "- restore backup to original path\n"
            "- delete backup from disk and state\n"
            "- inspect backup metadata"
        )

    def _build_available_text(self, backups) -> str:
        if not backups:
            return "[bold]Available backups[/bold]\n\nNo active backups are currently recorded."

        lines = []
        for backup in backups[:10]:
            lines.append(
                f"- {backup.backup_id}\n"
                f"  original: {backup.original_path}\n"
                f"  stored at: {backup.backup_path}\n"
                f"  exists on disk: {_yes_no(backup.exists_on_disk())}\n"
                f"  kind: {backup.kind}"
            )

        extra = ""
        if len(backups) > 10:
            extra = f"\n\nShowing 10 of {len(backups)} backups."

        return "[bold]Available backups[/bold]\n\n" + "\n\n".join(lines) + extra

    def _build_restorable_text(self, backups) -> str:
        if not backups:
            return "[bold]Restorable backups[/bold]\n\nNo restorable backups are available."

        lines = []
        for backup in backups[:10]:
            lines.append(
                f"- {backup.backup_id}\n"
                f"  restore target: {backup.original_path}\n"
                f"  backup source: {backup.backup_path}\n"
                f"  created at: {backup.created_at}\n"
                f"  restored before: {_yes_no(bool(backup.restored_at))}"
            )

        extra = ""
        if len(backups) > 10:
            extra = f"\n\nShowing 10 of {len(backups)} restorable backups."

        return (
            "[bold]Restorable backups[/bold]\n\n"
            + "\n\n".join(lines)
            + extra
            + "\n\nRestore behavior:\n"
            "- restore to the original recorded path\n"
            "- optionally overwrite an existing target\n"
            "- preserve backup metadata after restore"
        )

    def _build_deleted_text(self, backups) -> str:
        if not backups:
            return "[bold]Deleted backups[/bold]\n\nNo backups are marked as deleted."

        lines = []
        for backup in backups[:10]:
            lines.append(
                f"- {backup.backup_id}\n"
                f"  original: {backup.original_path}\n"
                f"  deleted at: {_safe(backup.deleted_at)}\n"
                f"  still on disk: {_yes_no(Path(backup.backup_path).exists())}"
            )

        extra = ""
        if len(backups) > 10:
            extra = f"\n\nShowing 10 of {len(backups)} deleted backups."

        return "[bold]Deleted backups[/bold]\n\n" + "\n\n".join(lines) + extra

    def _build_notes_text(self, available, restorable, deleted) -> str:
        notes: list[str] = []

        if not available:
            notes.append("- No backups have been registered yet.")
        else:
            notes.append("- Backup metadata is available for inspection.")

        if restorable:
            notes.append("- Restore operations can be wired directly from the recorded backup ids.")
        else:
            notes.append("- No backup currently qualifies for restore.")

        if available:
            notes.append("- Delete operations should remove the backup from disk and mark it as deleted in state.")

        if deleted:
            notes.append("- Deleted backup records remain visible for audit history.")

        return "\n".join(notes)
