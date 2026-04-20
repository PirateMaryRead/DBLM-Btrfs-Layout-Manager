from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import Button, Static

from core.logging import tail_log_buffer, tail_log_file
from ui.common import DBLMSectionScreen, DEFAULT_UI_STATE_FILE, safe_text
from ui.widgets.log_view import LogView


class LogsScreen(DBLMSectionScreen):
    """
    Global log screen for DBLM.

    Modes:
    - app: show global application logs
    - operation: show installer-style operation logs
    """

    BINDINGS = [
        ("r", "refresh_logs", "Refresh"),
        ("c", "clear_logs", "Clear"),
        ("t", "toggle_source", "Toggle Source"),
    ]

    source_mode: reactive[str] = reactive("memory")

    def __init__(
        self,
        state_file: str | Path = DEFAULT_UI_STATE_FILE,
        *,
        mode: str = "app",
        operation_name: str | None = None,
    ) -> None:
        super().__init__(state_file=state_file)
        self.mode = mode
        self.operation_name = operation_name
        self.last_error: str | None = None
        self.status_notice: str | None = None

        if self.mode == "operation":
            self.source_mode = "operation"

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
        self.log_screen_event(
            f"Opened logs screen (mode={self.mode}, source={self.source_mode}, operation={self.operation_name or 'n/a'})."
        )
        self.refresh_logs()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "refresh-logs":
            self.action_refresh_logs()
        elif event.button.id == "clear-logs":
            self.action_clear_logs()
        elif event.button.id == "toggle-source":
            self.action_toggle_source()

    def action_refresh_logs(self) -> None:
        self.status_notice = "Log view refreshed."
        self.log_screen_event(
            f"Logs refresh requested (mode={self.mode}, source={self.source_mode})."
        )
        self.refresh_logs()

    def action_clear_logs(self) -> None:
        app = getattr(self, "app", None)
        cleared = 0

        if self.mode == "operation":
            if app is not None and hasattr(app, "clear_operation_log"):
                existing = []
                if hasattr(app, "get_operation_log_entries"):
                    existing = app.get_operation_log_entries(limit=100000)
                cleared = len(existing)
                app.clear_operation_log()
            self.status_notice = f"Cleared {cleared} operation log line(s)."
            self.log_screen_event("Operation log buffer clear requested.")
        else:
            if app is not None and hasattr(app, "clear_logs"):
                cleared = app.clear_logs()

            if self.source_mode == "file":
                self.status_notice = (
                    f"Cleared {cleared} in-memory log line(s). Persistent file view is unchanged."
                )
            else:
                self.status_notice = f"Cleared {cleared} in-memory log line(s)."
            self.log_screen_event("Application log buffer clear requested.")

        self.refresh_logs()

    def action_toggle_source(self) -> None:
        if self.mode == "operation":
            self.status_notice = "Operation mode uses the operation log buffer only."
            self.log_screen_event("Toggle source ignored in operation mode.")
            self.refresh_logs()
            return

        self.source_mode = "file" if self.source_mode == "memory" else "memory"
        self.status_notice = f"Switched log source to {self.source_mode}."
        self.log_screen_event(f"Logs source switched to {self.source_mode}.")
        self.refresh_logs()

    def watch_source_mode(self, source_mode: str) -> None:
        try:
            status = self.query_one("#logs-status", Static)
            status.update(self._build_status_text(source_mode))
        except Exception:
            pass

    def refresh_logs(self) -> None:
        status = self.query_one("#logs-status", Static)
        log_view = self.query_one("#logs-view", LogView)

        try:
            lines, source, status_text = self._load_lines()

            log_view.title = "DBLM Operation Logs" if self.mode == "operation" else "DBLM Logs"
            log_view.set_subtitle(self._build_log_subtitle())
            log_view.set_status(status_text)
            log_view.load_rendered_lines(lines, source=source, clear_first=True)
            status.update(self._build_status_text(self.source_mode))
            self.last_error = None
        except Exception as exc:  # pragma: no cover
            self.last_error = str(exc)
            self.log_screen_error(f"Logs refresh failed: {exc}")
            status.update(self._build_status_text(self.source_mode))
            log_view.set_status("Failed to load logs.")
            log_view.load_rendered_lines(
                [f"Error while loading logs: {safe_text(self.last_error)}"],
                source="error",
                level="error",
                clear_first=True,
            )

    def _load_lines(self) -> tuple[list[str], str, str]:
        app = getattr(self, "app", None)

        if self.mode == "operation":
            lines: list[str]
            operation_status = {}
            if app is not None and hasattr(app, "get_operation_log_entries"):
                lines = app.get_operation_log_entries(limit=1000)
                if hasattr(app, "get_operation_log_status"):
                    operation_status = app.get_operation_log_status()
            else:
                lines = []

            op_name = self.operation_name or operation_status.get("name") or "operation"
            op_status = operation_status.get("status", "idle")
            line_count = operation_status.get("line_count", len(lines))
            status_text = (
                f"Showing installer-style operation log for {op_name}. "
                f"Status={op_status}. Lines={line_count}."
            )
            return lines, "operation", status_text

        if self.source_mode == "file":
            lines = tail_log_file(limit=500)
            return lines, "file", "Showing persistent log file."

        if app is not None and hasattr(app, "get_log_entries"):
            lines = app.get_log_entries(limit=500)
        else:
            lines = tail_log_buffer(limit=500)
        return lines, "memory", "Showing in-memory application log buffer."

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
            app = getattr(self, "app", None)
            label = self.operation_name or "current operation"
            if app is not None and hasattr(app, "get_operation_log_status"):
                meta = app.get_operation_log_status()
                label = str(meta.get("name") or label)
                status = safe_text(meta.get("status"), "idle")
                line_count = meta.get("line_count", 0)
                return f"Operation mode: {label} | status={status} | lines={line_count}"
            return f"Operation mode: {label}"

        return f"Source mode: {self.source_mode}"

    def _build_status_text(self, source_mode: str) -> str:
        lines = [
            "[bold]Log source[/bold]",
            "",
            f"Mode: {self.mode}",
            f"Source: {source_mode}",
            "Shortcuts:",
            "- R refresh",
            "- C clear current buffer",
        ]

        if self.mode == "operation":
            lines.append("- T disabled in operation mode")
            app = getattr(self, "app", None)
            if app is not None and hasattr(app, "get_operation_log_status"):
                meta = app.get_operation_log_status()
                lines.extend(
                    [
                        "",
                        f"Operation: {safe_text(meta.get('name'), 'none')}",
                        f"Status: {safe_text(meta.get('status'), 'idle')}",
                        f"Started: {safe_text(meta.get('started_at'), 'not started')}",
                        f"Finished: {safe_text(meta.get('finished_at'), 'not finished')}",
                        f"Success: {safe_text(meta.get('success'), 'unknown')}",
                        f"Lines: {meta.get('line_count', 0)}",
                    ]
                )
        else:
            lines.append("- T toggle memory/file")

        if self.status_notice:
            lines.extend(["", f"Notice: {safe_text(self.status_notice)}"])

        if self.last_error:
            lines.extend(["", f"Last error: {safe_text(self.last_error)}"])

        return "\n".join(lines)
