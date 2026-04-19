from __future__ import annotations

import time
import logging

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import Footer, Header, ListItem, ListView, Static

from core.state import StateManager
from core.system import EnvironmentSnapshot, scan_environment
from ui.screens.apply import ApplyScreen
from ui.screens.backups import BackupsScreen
from ui.screens.boot import BootScreen
from ui.screens.dashboard import DashboardScreen
from ui.screens.dependencies import DependenciesScreen
from ui.screens.plan import PlanScreen
from ui.screens.rollback import RollbackScreen
from ui.screens.snapper import SnapperScreen
from ui.screens.subvolumes import SubvolumeScreen
from ui.widgets.summary_box import SummaryBox

logger = logging.getLogger(__name__)

# How long (in seconds) the cached EnvironmentSnapshot is considered fresh.
# Screens that open within this window reuse the last scan result instead of
# spawning a new set of subprocesses (findmnt, bootctl, systemctl, …).
_ENV_CACHE_TTL: float = 5.0


MENU_ITEMS = [
    "Dashboard",
    "Dependencies",
    "Subvolumes",
    "Snapper",
    "Boot",
    "Plan",
    "Apply",
    "Revert",
    "Backups",
]


SCREEN_CLASSES = {
    "Dashboard": DashboardScreen,
    "Dependencies": DependenciesScreen,
    "Subvolumes": SubvolumeScreen,
    "Snapper": SnapperScreen,
    "Boot": BootScreen,
    "Plan": PlanScreen,
    "Apply": ApplyScreen,
    "Revert": RollbackScreen,
    "Backups": BackupsScreen,
}


class PlaceholderPanel(Static):
    """Fallback content area before a screen is opened."""

    def on_mount(self) -> None:
        self.update(
            "[bold]Welcome[/bold]\n\n"
            "Select a section from the left menu and press Enter."
        )


class DBLMApp(App[None]):
    """DBLM — Btrfs Layout Manager."""

    CSS_PATH = "ui/styles.tcss"
    TITLE = "DBLM — Btrfs Layout Manager"
    SUB_TITLE = "Interactive Btrfs layout management"

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("up", "cursor_up", "Up"),
        ("down", "cursor_down", "Down"),
        ("enter", "open_section", "Open"),
        ("r", "refresh_summary", "Refresh"),
    ]

    selected_section: reactive[str] = reactive("Dashboard")

    def __init__(self, state_file: str = "data/state.json") -> None:
        super().__init__()

        # FIX: single StateManager instance shared across all screens.
        # Previously each screen created its own instance, causing the
        # state.json to be read from disk every time a screen was opened
        # and creating a risk of two screens overwriting each other's state.
        self.state_manager = StateManager(state_file)

        # FIX: cached environment snapshot shared across all screens.
        # Previously scan_environment() was called independently in each of
        # the 8 screens plus SummaryBox, spawning 15-20 subprocesses every
        # time the user navigated. Now all screens call self.app.get_environment()
        # which returns a cached result within the TTL window.
        self._env_cache: EnvironmentSnapshot | None = None
        self._env_cache_time: float = 0.0

    # ------------------------------------------------------------------ #
    # Shared environment cache                                             #
    # ------------------------------------------------------------------ #

    def get_environment(self, *, force: bool = False) -> EnvironmentSnapshot:
        """
        Return a cached EnvironmentSnapshot, refreshing when stale.

        The cache is valid for _ENV_CACHE_TTL seconds. Pass force=True to
        bypass the TTL and force a fresh scan immediately (e.g. after the
        user explicitly presses Refresh).

        All screens and widgets should call this instead of scan_environment()
        directly so subprocesses are not duplicated across the UI.
        """
        now = time.monotonic()
        cache_is_stale = (now - self._env_cache_time) > _ENV_CACHE_TTL

        if force or self._env_cache is None or cache_is_stale:
            logger.debug("Refreshing environment snapshot (force=%s)", force)
            self._env_cache = scan_environment()
            self._env_cache_time = now

        return self._env_cache

    def invalidate_environment_cache(self) -> None:
        """
        Force the next get_environment() call to perform a fresh scan.

        Call this after any operation that modifies the system (e.g. after
        applying subvolume changes or modifying fstab) so that the next
        screen refresh reflects the real post-change state.
        """
        self._env_cache = None
        self._env_cache_time = 0.0

    # ------------------------------------------------------------------ #
    # UI composition                                                       #
    # ------------------------------------------------------------------ #

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        with Vertical(id="app-shell"):
            yield SummaryBox(id="summary-box")

            with Horizontal(id="main-layout"):
                with Container(id="sidebar"):
                    yield Static("[bold]Sections[/bold]", classes="panel-title")
                    menu = ListView(id="menu")
                    for item in MENU_ITEMS:
                        menu.append(ListItem(Static(item)))
                    yield menu

                with Container(id="content-area"):
                    yield Static("[bold]Content[/bold]", classes="panel-title")
                    yield PlaceholderPanel(id="content-panel")

        yield Footer()

    def on_mount(self) -> None:
        menu = self.query_one("#menu", ListView)
        menu.index = 0

    # ------------------------------------------------------------------ #
    # Actions and navigation                                               #
    # ------------------------------------------------------------------ #

    def action_cursor_up(self) -> None:
        menu = self.query_one("#menu", ListView)
        if menu.index is None:
            menu.index = 0
            return
        menu.index = max(0, menu.index - 1)

    def action_cursor_down(self) -> None:
        menu = self.query_one("#menu", ListView)
        if menu.index is None:
            menu.index = 0
            return
        menu.index = min(len(MENU_ITEMS) - 1, menu.index + 1)

    def action_open_section(self) -> None:
        menu = self.query_one("#menu", ListView)
        index = menu.index or 0
        self._open_section(MENU_ITEMS[index])

    def action_refresh_summary(self) -> None:
        # Force a fresh scan when the user explicitly presses R so the
        # summary always reflects the current system state on demand.
        self.invalidate_environment_cache()
        summary = self.query_one("#summary-box", SummaryBox)
        summary.refresh_summary()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id != "menu":
            return
        index = event.list_view.index or 0
        self._open_section(MENU_ITEMS[index])

    def _open_section(self, section: str) -> None:
        self.selected_section = section
        screen_cls = SCREEN_CLASSES[section]
        self.push_screen(screen_cls())

    def watch_selected_section(self, section: str) -> None:
        summary = self.query_one("#summary-box", SummaryBox)
        summary.refresh_summary()


def main() -> None:
    DBLMApp().run()


if __name__ == "__main__":
    main()
