from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import Screen
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


class MainMenuScreen(Screen[None]):
    """
    Main navigation screen for DBLM.

    Navigation is unified around standalone screens:
    - this screen is the launcher
    - each section opens as its own Screen
    - the app provides shared state and environment caching
    """

    BINDINGS = [
        ("up", "cursor_up", "Up"),
        ("down", "cursor_down", "Down"),
        ("enter", "open_section", "Open"),
        ("r", "refresh_summary", "Refresh"),
    ]

    selected_section: reactive[str] = reactive("Dashboard")

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
                    yield Static("[bold]Overview[/bold]", classes="panel-title")
                    yield Static(
                        "[bold]DBLM — Btrfs Layout Manager[/bold]\n\n"
                        "Use the left menu to open a section.\n\n"
                        "Navigation:\n"
                        "- Enter: open selected section\n"
                        "- R: refresh summary\n"
                        "- B: go back from any opened screen\n"
                        "- Q: quit the app",
                        id="content-panel",
                    )

        yield Footer()

    def on_mount(self) -> None:
        menu = self.query_one("#menu", ListView)
        menu.index = 0
        self.selected_section = MENU_ITEMS[0]

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
        self.app.invalidate_environment_cache()
        summary = self.query_one("#summary-box", SummaryBox)
        summary.refresh_summary()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id != "menu":
            return
        index = event.list_view.index or 0
        self.selected_section = MENU_ITEMS[index]
        self._open_section(self.selected_section)

    def watch_selected_section(self, section: str) -> None:
        content = self.query_one("#content-panel", Static)
        content.update(
            "[bold]DBLM — Btrfs Layout Manager[/bold]\n\n"
            f"Selected section: {section}\n\n"
            "Press Enter to open it.\n"
            "Press R to refresh the environment summary."
        )

    def _open_section(self, section: str) -> None:
        self.selected_section = section
        screen_cls = SCREEN_CLASSES[section]
        self.app.push_screen(screen_cls())


class DBLMApp(App[None]):
    """DBLM — Btrfs Layout Manager."""

    CSS_PATH = "ui/styles.tcss"
    TITLE = "DBLM — Btrfs Layout Manager"
    SUB_TITLE = "Interactive Btrfs layout management"

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("b", "back", "Back"),
    ]

    def __init__(self, state_file: str | Path = "data/state.json") -> None:
        super().__init__()
        self.state_file = Path(state_file)
        self.state_manager = StateManager(self.state_file)
        self._environment_cache: EnvironmentSnapshot | None = None

    def on_mount(self) -> None:
        self.push_screen(MainMenuScreen())

    def action_back(self) -> None:
        """Return to the previous screen when possible."""
        if len(self.screen_stack) > 1:
            self.pop_screen()

    def get_environment(self, *, force: bool = False) -> EnvironmentSnapshot:
        """
        Return a cached environment snapshot.

        Set force=True to rescan the system.
        """
        if force or self._environment_cache is None:
            self._environment_cache = scan_environment()
        return self._environment_cache

    def invalidate_environment_cache(self) -> None:
        """Clear the cached environment snapshot."""
        self._environment_cache = None


def main() -> None:
    DBLMApp().run()


if __name__ == "__main__":
    main()
