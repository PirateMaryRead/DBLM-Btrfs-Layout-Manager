from __future__ import annotations

from textual.widgets import Static

from core.logging import get_logger
from ui.common import safe_text, yes_no


class SummaryBox(Static):
    """Top summary widget for DBLM."""

    DEFAULT_TEXT = """
[bold]DBLM — Btrfs Layout Manager[/bold]
Interactive TUI for auditing and managing Btrfs layouts on existing Linux installations.
""".strip()

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.logger = get_logger("ui.summary_box")

    def on_mount(self) -> None:
        self.update(self.DEFAULT_TEXT)
        self.refresh_summary()

    def refresh_summary(self) -> None:
        try:
            app = self.app
            if not hasattr(app, "get_environment") or not hasattr(app, "state_manager"):
                self.update(self.DEFAULT_TEXT)
                return

            snapshot = app.get_environment()
            state_summary = app.state_manager.summarize()

            self.update(
                "[bold]DBLM — Btrfs Layout Manager[/bold]\n"
                f"Host: {safe_text(snapshot.hostname)} | "
                f"Distro: {safe_text(snapshot.distro)} | "
                f"Kernel: {safe_text(snapshot.kernel)}\n"
                f"Root FS: {safe_text(snapshot.root_fs.fstype)} | "
                f"Root subvol: {safe_text(snapshot.root_fs.subvol)} | "
                f"/home Btrfs: {yes_no(snapshot.home_fs.is_btrfs)}\n"
                f"Boot: {safe_text(snapshot.bootloader.detected)} | "
                f"Snapper: {yes_no('snapper' in snapshot.dependencies.optional_found)} | "
                f"Required deps OK: {yes_no(snapshot.dependencies.required_ok)}\n"
                f"Runs: {state_summary.get('runs_total', 0)} | "
                f"Backups: {state_summary.get('backups_available', 0)} | "
                f"Restorable: {state_summary.get('backups_restorable', 0)}"
            )
        except Exception as exc:  # pragma: no cover - defensive UI path
            self.logger.exception("Failed to refresh summary box.")
            self.update(
                "[bold]DBLM — Btrfs Layout Manager[/bold]\n"
                f"Summary refresh failed: {safe_text(exc)}"
            )
