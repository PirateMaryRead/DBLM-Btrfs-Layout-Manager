from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable

from textual.widgets import Static


@dataclass(slots=True)
class LogEntry:
    """A single log line rendered by the UI."""

    level: str = "info"
    message: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().strftime("%H:%M:%S"))
    source: str = "app"
    raw_line: str | None = None

    def render(self) -> str:
        """
        Render the entry.

        When raw_line is present, it is returned exactly as received. This is
        important for application and operation logs that are already formatted.
        """
        if self.raw_line is not None:
            return self.raw_line

        level = self.level.upper().strip() or "INFO"
        source = self.source.strip() or "app"

        prefix_map = {
            "DEBUG": "[DEBUG]",
            "INFO": "[INFO]",
            "WARNING": "[WARN]",
            "WARN": "[WARN]",
            "ERROR": "[ERROR]",
            "CRITICAL": "[CRITICAL]",
        }
        prefix = prefix_map.get(level, f"[{level}]")
        return f"[{self.timestamp}] {prefix} {source}: {self.message}"


class LogView(Static):
    """
    Console-like log widget for DBLM.

    Supports:
    - in-memory log lines
    - append/extend behavior
    - console-style rendering
    - optional title/subtitle/status line
    - pre-rendered log lines from logging backends
    """

    def __init__(
        self,
        title: str = "Logs",
        *,
        subtitle: str = "",
        max_entries: int = 5000,
        show_status_line: bool = True,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.title = title
        self.subtitle = subtitle
        self.max_entries = max_entries
        self.show_status_line = show_status_line
        self.entries: list[LogEntry] = []
        self.status_text: str = "Idle."

    def on_mount(self) -> None:
        self.refresh_log()

    def set_status(self, text: str) -> None:
        """Set a short status line shown above the log body."""
        self.status_text = text.strip() or "Idle."
        self.refresh_log()

    def set_subtitle(self, subtitle: str) -> None:
        """Update the subtitle text."""
        self.subtitle = subtitle
        self.refresh_log()

    def clear(self) -> None:
        """Remove all log entries."""
        self.entries.clear()
        self.status_text = "Log buffer cleared."
        self.refresh_log()

    def append(
        self,
        message: str,
        *,
        level: str = "info",
        source: str = "app",
        timestamp: str | None = None,
    ) -> None:
        """Append a new structured log line and refresh the widget."""
        self.entries.append(
            LogEntry(
                level=level,
                message=message,
                source=source,
                timestamp=timestamp or datetime.now().strftime("%H:%M:%S"),
            )
        )
        self._trim()
        self.refresh_log()

    def append_raw(self, line: str) -> None:
        """Append a pre-rendered log line without modifying its format."""
        text = str(line).rstrip()
        if not text:
            return
        self.entries.append(LogEntry(raw_line=text))
        self._trim()
        self.refresh_log()

    def extend(
        self,
        messages: Iterable[str],
        *,
        level: str = "info",
        source: str = "app",
    ) -> None:
        """Append multiple structured log lines."""
        now = datetime.now().strftime("%H:%M:%S")
        for message in messages:
            self.entries.append(
                LogEntry(
                    level=level,
                    message=str(message),
                    source=source,
                    timestamp=now,
                )
            )
        self._trim()
        self.refresh_log()

    def load_rendered_lines(
        self,
        lines: Iterable[str],
        *,
        source: str = "buffer",
        level: str = "info",
        clear_first: bool = True,
    ) -> None:
        """
        Load already-rendered log lines from a logging backend.

        These lines are preserved exactly as they arrive, which avoids adding a
        second timestamp/level prefix on top of logger output.
        """
        if clear_first:
            self.entries.clear()

        for line in lines:
            text = str(line).rstrip()
            if not text:
                continue
            self.entries.append(LogEntry(raw_line=text, source=source, level=level))

        self._trim()
        self.refresh_log()

    def refresh_log(self) -> None:
        """Render the current log buffer."""
        parts: list[str] = [f"[bold]{self.title}[/bold]"]

        if self.subtitle:
            parts.append("")
            parts.append(self.subtitle)

        if self.show_status_line:
            parts.append("")
            parts.append(f"[bold]Status:[/bold] {self.status_text}")

        parts.append("")
        parts.append("[bold]Output[/bold]")
        parts.append("")

        if not self.entries:
            parts.append("No log entries yet.")
        else:
            parts.extend(entry.render() for entry in self.entries)

        self.update("\n".join(parts))

    def line_count(self) -> int:
        """Return the number of buffered entries."""
        return len(self.entries)

    def summary(self) -> dict[str, int]:
        """Return counts grouped by normalized level for structured entries."""
        counts: dict[str, int] = {}
        for entry in self.entries:
            if entry.raw_line is not None:
                counts["RAW"] = counts.get("RAW", 0) + 1
                continue
            level = entry.level.upper()
            counts[level] = counts.get(level, 0) + 1
        return counts

    def _trim(self) -> None:
        """Keep only the most recent entries."""
        if len(self.entries) > self.max_entries:
            self.entries = self.entries[-self.max_entries :]
