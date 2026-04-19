from __future__ import annotations

from textual.widgets import Static


def _safe(value: str | None, fallback: str = "unknown") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text if text else fallback


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


class SummaryBox(Static):
    """Top summary widget for DBLM."""

    DEFAULT_TEXT = """
[bold]DBLM — Btrfs Layout Manager[/bold]
Interactive TUI for auditing and managing Btrfs layouts on existing Linux installations.
""".strip()

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        # FIX: no longer owns a StateManager or calls scan_environment()
        # directly. Both are now accessed via self.app (DBLMApp) which holds
        # a single shared instance and a cached environment snapshot.

    def on_mount(self) -> None:
        self.update(self.DEFAULT_TEXT)
        self.refresh_summary()

    def refresh_summary(self) -> None:
        try:
            # FIX: use the app-level shared cache and state manager instead
            # of creating new instances or calling scan_environment() directly.
            from app import DBLMApp
            app = self.app
            if not isinstance(app, DBLMApp):
                return

            snapshot = app.get_environment()
            state_summary = app.state_manager.summarize()

            self.update(
                "[bold]DBLM — Btrfs Layout Manager[/bold]\n"
                f"Host: {_safe(snapshot.hostname)} | "
                f"Distro: {_safe(snapshot.distro)} | "
                f"Kernel: {_safe(snapshot.kernel)}\n"
                f"Root FS: {_safe(snapshot.root_fs.fstype)} | "
                f"Root subvol: {_safe(snapshot.root_fs.subvol)} | "
                f"/home Btrfs: {_yes_no(snapshot.home_fs.is_btrfs)}\n"
                f"Boot: {_safe(snapshot.bootloader.detected)} | "
                f"Snapper: {_yes_no('snapper' in snapshot.dependencies.optional_found)} | "
                f"Required deps OK: {_yes_no(snapshot.dependencies.required_ok)}\n"
                f"Runs: {state_summary.get('runs_total', 0)} | "
                f"Backups: {state_summary.get('backups_available', 0)} | "
                f"Restorable: {state_summary.get('backups_restorable', 0)}"
            )
        except Exception as exc:  # pragma: no cover - defensive UI path
            self.update(
                "[bold]DBLM — Btrfs Layout Manager[/bold]\n"
                f"Summary refresh failed: {exc}"
            )
