from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import Button, Static

from core.logging import tail_log_buffer, tail_log_file
from ui.common import DBLMSectionScreen, safe_text
from ui.widgets.log_view import LogView


class LogsScreen(DBLMSectionScreen):
    """
    Global log screen for DBLM.

    Modes:
    - app: show global application logs
    - operation: reserved for future apply/revert execution streams
    """

    BINDINGS = [
        ("r", "refresh_logs", "Refresh"),
        ("c", "clear_logs", "Clear"),
        ("t", "toggle_source", "Toggle Source"),
    ]

    source_mode: reactive[str] = reactive("memory")

    def __init__(
        self,
        state_file: str | Path = "data/state.json",
        *,
        mode: str = "app",
        operation_name: str | None = None,
    ) -> None:
        super().__init__(state_file=state_file)
        self.mode = mode
        self.operation_name = operation_name
        self.last_error: str | None = None

    def compose_body(self) -> ComposeResult:
        with Vertical(id="logs-root"):
            yield Static("[bold]Logs[/bold]", id="logs-title")
            yield Static(self._build_subtitle(), id="logs-subtitle")

            with Horizontal(id="logs-actions"):
                yield Button("Refresh", id="refresh-logs", variant="primary")
                yield Button("Clear Buffer", id="clear-logs")
                yield Button("Toggle Source", id="toggle-source")

            yield Static(id="logs-status")
            yield LogView(
                title="DBLM Logs",
                subtitle="Console-style output similar to package managers and installers.",
                id="logs-view",
            )

    def on_mount(self) -> None:
        self.log_screen_event(f"Opened logs screen (mode={self.mode}, source={self.source_mode}).")
        self.refresh_logs()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "refresh-logs":
            self.refresh_logs()
        elif event.button.id == "clear-logs":
            self.action_clear_logs()
        elif event.button.id == "toggle-source":
            self.action_toggle_source()

    def action_refresh_logs(self) -> None:
        self.refresh_logs()

    def action_clear_logs(self) -> None:
        app = getattr(self, "app", None)
        if app is not None and hasattr(app, "clear_logs"):
            app.clear_logs()
        self.log_screen_event("Log buffer clear requested from logs screen.")
        self.refresh_logs()

    def action_toggle_source(self) -> None:
        self.source_mode = "file" if self.source_mode == "memory" else "memory"
        self.log_screen_event(f"Logs source switched to {self.source_mode}.")
        self.refresh_logs()

    def watch_source_mode(self, source_mode: str) -> None:
        status = self.query_one("#logs-status", Static)
        status.update(self._build_status_text(source_mode))

    def refresh_logs(self) -> None:
        status = self.query_one("#logs-status", Static)
        log_view = self.query_one("#logs-view", LogView)

        try:
            if self.source_mode == "file":
                lines = tail_log_file(limit=500)
                source = "file"
                status_text = "Showing persistent log file."
            else:
                app = getattr(self, "app", None)
                if app is not None and hasattr(app, "get_log_entries"):
                    lines = app.get_log_entries(limit=500)
                else:
                    lines = tail_log_buffer(limit=500)
                source = "memory"
                status_text = "Showing in-memory application log buffer."

            log_view.set_subtitle(self._build_log_subtitle())
            log_view.set_status(status_text)
            log_view.load_rendered_lines(lines, source=source, clear_first=True)
            status.update(self._build_status_text(self.source_mode))
            self.last_error = None
        except Exception as exc:  # pragma: no cover
            self.last_error = str(exc)
            status.update(self._build_status_text(self.source_mode))
            log_view.set_status("Failed to load logs.")
            log_view.load_rendered_lines(
                [f"Error while loading logs: {safe_text(self.last_error)}"],
                source="error",
                level="error",
                clear_first=True,
            )

    def _build_subtitle(self) -> str:
        if self.mode == "operation":
            operation_label = self.operation_name or "current operation"
            return (
                "Execution log view for DBLM operations, intended to look like an "
                f"installer/progress console. Current target: {operation_label}."
            )

        return (
            "Global application log view. This screen shows the app log buffer or "
            "the persistent log file."
        )

    def _build_log_subtitle(self) -> str:
        if self.mode == "operation":
            label = self.operation_name or "current operation"
            return f"Operation mode: {label}"
        return f"Source mode: {self.source_mode}"

    def _build_status_text(self, source_mode: str) -> str:
        error_text = ""
        if self.last_error:
            error_text = f"\nLast error: {safe_text(self.last_error)}"

        return (
            "[bold]Log source[/bold]\n\n"
            f"Mode: {self.mode}\n"
            f"Source: {source_mode}\n"
            "Shortcuts:\n"
            "- R refresh\n"
            "- C clear in-memory buffer\n"
            "- T toggle memory/file"
            f"{error_text}"
        )
