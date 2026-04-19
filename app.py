from __future__ import annotations

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import Footer, Header, ListItem, ListView, Static

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
