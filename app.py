from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import ListItem, ListView, Static

from core.state import StateManager
from core.system import EnvironmentSnapshot, scan_environment
from ui.common import DBLMSectionScreen, HelpScreen
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
    "Help",
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
    "Help": HelpScreen,
}


SECTION_PREVIEWS = {
    "Dashboard": "Audit the current system, inspect Btrfs layout details, and review recorded state.",
    "Dependencies": "Inspect required and optional packages for DBLM features.",
    "Subvolumes": "Choose profiles, inspect targets, and prepare subvolume layout changes.",
    "Snapper": "Inspect Snapper availability, configs, timers, and layout readiness.",
    "Boot": "Inspect GRUB, grub-btrfs, systemd-boot, and snapshot boot readiness.",
    "Plan": "Review the current environment and expected DBLM-managed operations.",
    "Apply": "Review execution readiness before enabling destructive operations.",
    "Revert": "Inspect rollback metadata, restore options, and subvolume removal paths.",
    "Backups": "Inspect recorded backups, restore options, and delete operations.",
    "Help": "Show keyboard shortcuts and navigation help.",
}


class MainMenuScreen(DBLMSectionScreen):
    """
    Main navigation screen for DBLM.

    This is the launcher screen. All other sections are opened as standalone
    screens, while the app itself provides shared state and environment caching.
    """

    BINDINGS = [
        ("up", "cursor_up", "Up"),
        ("down", "cursor_down", "Down"),
        ("enter", "open_section", "Open"),
        ("r", "refresh_summary", "Refresh"),
    ]

    selected_section: reactive[str] = reactive("Dashboard")

    def compose_body(self) -> ComposeResult:
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
                    yield Static(id="content-panel")

    def on_mount(self) -> None:
        menu = self.query_one("#menu", ListView)
        menu.index = 0
        self.selected_section = MENU_ITEMS[0]
        self._refresh_summary_box()

    def action_cursor_up(self) -> None:
        menu = self.query_one("#menu", ListView)
        if menu.index is None:
            menu.index = 0
            return
        menu.index = max(0, menu.index - 1)
        self.selected_section = MENU_ITEMS[menu.index]

    def action_cursor_down(self) -> None:
        menu = self.query_one("#menu", ListView)
        if menu.index is None:
            menu.index = 0
            return
        menu.index = min(len(MENU_ITEMS) - 1, menu.index + 1)
        self.selected_section = MENU_ITEMS[menu.index]

    def action_open_section(self) -> None:
        menu = self.query_one("#menu", ListView)
        index = menu.index or 0
        self._open_section(MENU_ITEMS[index])

    def action_refresh_summary(self) -> None:
        self.app.invalidate_environment_cache()
        self._refresh_summary_box()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id != "menu":
            return
        index = event.list_view.index or 0
        self.selected_section = MENU_ITEMS[index]
        self._open_section(self.selected_section)

    def watch_selected_section(self, section: str) -> None:
        content = self.query_one("#content-panel", Static)
        preview = SECTION_PREVIEWS.get(section, "No preview available.")
        content.update(
            "[bold]DBLM — Btrfs Layout Manager[/bold]\n\n"
            f"Selected section: {section}\n\n"
            f"{preview}\n\n"
            "Keyboard shortcuts:\n"
            "- Enter: open selected section\n"
            "- R: refresh summary\n"
            "- F1-F8: direct navigation\n"
            "- A: Apply\n"
            "- V: Revert\n"
            "- M: Main menu\n"
            "- B: Back\n"
            "- Q: Quit"
        )

    def _open_section(self, section: str) -> None:
        if section == "Help":
            self.app.action_open_help()
            return

        self.selected_section = section
        screen_cls = SCREEN_CLASSES[section]
        self.app.open_section_screen(screen_cls)

    def _refresh_summary_box(self) -> None:
        summary = self.query_one("#summary-box", SummaryBox)
        summary.refresh_summary()


class DBLMApp(App[None]):
    """DBLM — Btrfs Layout Manager."""

    CSS_PATH = "ui/styles.tcss"
    TITLE = "DBLM — Btrfs Layout Manager"
    SUB_TITLE = "Interactive Btrfs layout management"

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("b", "back", "Back"),
        ("m", "main_menu", "Main Menu"),
        ("f1", "open_dashboard", "F1 Dashboard"),
        ("f2", "open_dependencies", "F2 Dependencies"),
        ("f3", "open_subvolumes", "F3 Subvolumes"),
        ("f4", "open_snapper", "F4 Snapper"),
        ("f5", "open_boot", "F5 Boot"),
        ("f6", "open_plan", "F6 Plan"),
        ("f7", "open_backups", "F7 Backups"),
        ("f8", "open_help", "F8 Help"),
        ("a", "open_apply", "Apply"),
        ("v", "open_revert", "Revert"),
    ]

    def __init__(self, state_file: str | Path = "data/state.json") -> None:
        super().__init__()
        self.state_file = Path(state_file)
        self.state_manager = StateManager(self.state_file)
        self._environment_cache: EnvironmentSnapshot | None = None

    def on_mount(self) -> None:
        self.push_screen(MainMenuScreen(state_file=self.state_file))

    def action_back(self) -> None:
        """Return to the previous screen when possible."""
        if len(self.screen_stack) > 1:
            self.pop_screen()
        self.call_after_refresh(self._refresh_main_menu_summary_if_visible)

    def action_main_menu(self) -> None:
        """Return to the main menu screen."""
        while len(self.screen_stack) > 1:
            self.pop_screen()
        self.call_after_refresh(self._refresh_main_menu_summary_if_visible)

    def action_open_dashboard(self) -> None:
        self.open_section_screen(DashboardScreen)

    def action_open_dependencies(self) -> None:
        self.open_section_screen(DependenciesScreen)

    def action_open_subvolumes(self) -> None:
        self.open_section_screen(SubvolumeScreen)

    def action_open_snapper(self) -> None:
        self.open_section_screen(SnapperScreen)

    def action_open_boot(self) -> None:
        self.open_section_screen(BootScreen)

    def action_open_plan(self) -> None:
        self.open_section_screen(PlanScreen)

    def action_open_backups(self) -> None:
        self.open_section_screen(BackupsScreen)

    def action_open_help(self) -> None:
        self.open_section_screen(HelpScreen)

    def action_open_apply(self) -> None:
        self.open_section_screen(ApplyScreen)

    def action_open_revert(self) -> None:
        self.open_section_screen(RollbackScreen)

    def open_section_screen(self, screen_cls: type[DBLMSectionScreen]) -> None:
        """
        Open a section screen from anywhere in the app.

        Keeps the main menu as the base screen and replaces the currently open
        section instead of stacking many section screens.
        """
        while len(self.screen_stack) > 1:
            self.pop_screen()

        if screen_cls is MainMenuScreen:
            self.call_after_refresh(self._refresh_main_menu_summary_if_visible)
            return

        self.push_screen(screen_cls(state_file=self.state_file))

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

    def _refresh_main_menu_summary_if_visible(self) -> None:
        if isinstance(self.screen, MainMenuScreen):
            try:
                summary = self.screen.query_one("#summary-box", SummaryBox)
                summary.refresh_summary()
            except Exception:
                pass


def main() -> None:
    DBLMApp().run()


if __name__ == "__main__":
    main()
