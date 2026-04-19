from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable

from textual.widgets import Static


@dataclass(slots=True)
class LogEntry:
    """A single log line rendered by the UI."""

    level: str
    message: str
    timestamp: str = field(default_factory=lambda: datetime.now().strftime("%H:%M:%S"))

    def render(self) -> str:
        level = self.level.upper().strip() or "INFO"
        return f"[{self.timestamp}] {level}: {self.message}"


class LogView(Static):
    """Simple in-memory log widget for DBLM screens."""

    DEFAULT_TEXT = "[bold]Log[/bold]\n\nNo log entries yet."

    def __init__(self, max_entries: int = 200, **kwargs) -> None:
        super().__init__(**kwargs)
        self.max_entries = max_entries
        self.entries: list[LogEntry] = []

    def on_mount(self) -> None:
        self.update(self.DEFAULT_TEXT)

    def clear(self) -> None:
        """Remove all log entries."""
        self.entries.clear()
        self.update(self.DEFAULT_TEXT)

    def append(self, message: str, *, level: str = "info") -> None:
        """Append a new log line and refresh the widget."""
        self.entries.append(LogEntry(level=level, message=message))
        self._trim()
        self.refresh_log()

    def extend(self, messages: Iterable[str], *, level: str = "info") -> None:
        """Append multiple log lines."""
        for message in messages:
            self.entries.append(LogEntry(level=level, message=message))
        self._trim()
        self.refresh_log()

    def refresh_log(self) -> None:
        """Render the current log buffer."""
        if not self.entries:
            self.update(self.DEFAULT_TEXT)
            return

        body = "\n".join(entry.render() for entry in self.entries)
        self.update(f"[bold]Log[/bold]\n\n{body}")

    def _trim(self) -> None:
        """Keep only the most recent entries."""
        if len(self.entries) > self.max_entries:
            self.entries = self.entries[-self.max_entries :]
