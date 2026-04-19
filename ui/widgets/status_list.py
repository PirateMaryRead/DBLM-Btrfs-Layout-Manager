from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from textual.widgets import Static


@dataclass(slots=True)
class StatusItem:
    """A labeled status row for UI summaries."""

    label: str
    value: str
    state: str = "info"

    def render(self) -> str:
        prefix_map = {
            "ok": "[OK]",
            "warn": "[WARN]",
            "error": "[ERROR]",
            "info": "[INFO]",
        }
        prefix = prefix_map.get(self.state, "[INFO]")
        return f"{prefix} {self.label}: {self.value}"


class StatusList(Static):
    """Simple status list widget for DBLM screens."""

    def __init__(self, title: str = "Status", **kwargs) -> None:
        super().__init__(**kwargs)
        self.title = title
        self.items: list[StatusItem] = []

    def on_mount(self) -> None:
        self.refresh_status()

    def set_items(self, items: Iterable[StatusItem]) -> None:
        """Replace all current status items."""
        self.items = list(items)
        self.refresh_status()

    def add_item(self, label: str, value: str, *, state: str = "info") -> None:
        """Append a single status item."""
        self.items.append(StatusItem(label=label, value=value, state=state))
        self.refresh_status()

    def clear(self) -> None:
        """Clear all items."""
        self.items.clear()
        self.refresh_status()

    def refresh_status(self) -> None:
        """Render the current status list."""
        if not self.items:
            self.update(f"[bold]{self.title}[/bold]\n\nNo status items.")
            return

        body = "\n".join(item.render() for item in self.items)
        self.update(f"[bold]{self.title}[/bold]\n\n{body}")
