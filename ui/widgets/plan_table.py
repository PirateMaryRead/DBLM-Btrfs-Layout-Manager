from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from textual.widgets import Static


@dataclass(slots=True)
class PlanRow:
    """A single row in a DBLM execution plan summary."""

    category: str
    item: str
    status: str = "pending"
    details: str = ""

    def render(self) -> str:
        status_map = {
            "pending": "[PENDING]",
            "ready": "[READY]",
            "warn": "[WARN]",
            "skip": "[SKIP]",
            "done": "[DONE]",
            "error": "[ERROR]",
        }
        prefix = status_map.get(self.status, "[PENDING]")

        if self.details:
            return f"{prefix} {self.category} | {self.item} | {self.details}"
        return f"{prefix} {self.category} | {self.item}"


class PlanTable(Static):
    """Simple text-based plan table for DBLM screens."""

    def __init__(self, title: str = "Plan", **kwargs) -> None:
        super().__init__(**kwargs)
        self.title = title
        self.rows: list[PlanRow] = []

    def on_mount(self) -> None:
        self.refresh_table()

    def set_rows(self, rows: Iterable[PlanRow]) -> None:
        """Replace all current plan rows."""
        self.rows = list(rows)
        self.refresh_table()

    def add_row(
        self,
        category: str,
        item: str,
        *,
        status: str = "pending",
        details: str = "",
    ) -> None:
        """Append a single plan row."""
        self.rows.append(
            PlanRow(
                category=category,
                item=item,
                status=status,
                details=details,
            )
        )
        self.refresh_table()

    def clear(self) -> None:
        """Clear all rows."""
        self.rows.clear()
        self.refresh_table()

    def summary(self) -> dict[str, int]:
        """Return counts grouped by row status."""
        counts: dict[str, int] = {}
        for row in self.rows:
            counts[row.status] = counts.get(row.status, 0) + 1
        return counts

    def refresh_table(self) -> None:
        """Render the current plan rows."""
        if not self.rows:
            self.update(f"[bold]{self.title}[/bold]\n\nNo plan items.")
            return

        counts = self.summary()
        summary_line = " | ".join(
            f"{key}={value}" for key, value in sorted(counts.items())
        )

        body = "\n".join(row.render() for row in self.rows)
        self.update(
            f"[bold]{self.title}[/bold]\n\n"
            f"{summary_line}\n\n"
            f"{body}"
        )
