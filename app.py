from __future__ import annotations

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import Footer, Header, ListItem, ListView, Static


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


SECTION_CONTENT = {
    "Dashboard": """
[bold]DBLM — Btrfs Layout Manager[/bold]

Interactive TUI for auditing and managing Btrfs layouts on existing Linux installations.

This screen will show:
- root Btrfs status
- /home topology and filesystem type
- detected bootloader
- Snapper status
- dependency status
- fstab warnings
- pending rollback items
- available backups
""".strip(),
    "Dependencies": """
[bold]Dependencies[/bold]

This section will manage:
- required runtime tools
- optional packages
- apt-based installation checks
- feature-specific package validation
""".strip(),
    "Subvolumes": """
[bold]Subvolumes[/bold]

This section will manage:
- system subvolumes
- optional /home handling when /home is Btrfs
- profile-based selection
- migration planning
""".strip(),
    "Snapper": """
[bold]Snapper[/bold]

This section will manage:
- Snapper detection
- configuration checks
- layout compatibility
- timeline and cleanup integration
""".strip(),
    "Boot": """
[bold]Boot[/bold]

This section will manage:
- GRUB detection
- grub-btrfs integration
- systemd-boot integration
- bootloader regeneration planning
""".strip(),
    "Plan": """
[bold]Plan[/bold]

This section will summarize:
- packages to install
- subvolumes to create
- directories to migrate
- fstab changes
- backups to create
- services to stop
""".strip(),
    "Apply": """
[bold]Apply[/bold]

This section will execute the current plan and show:
- step-by-step progress
- command output summaries
- warnings
- final validation results
""".strip(),
    "Revert": """
[bold]Revert[/bold]

This section will support:
- restoring original directories
- reverting fstab changes
- removing created subvolumes
- rolling back the last run
""".strip(),
    "Backups": """
[bold]Backups[/bold]

This section will support:
- listing created backups
- restoring a backup
- deleting selected backups
- cleaning up orphaned backups
""".strip(),
}


class SummaryBox(Static):
    """Top summary placeholder. Will later be connected to system inspection."""

    DEFAULT_TEXT = """
[bold]System summary[/bold]
Root filesystem: unknown
Root Btrfs: not scanned
Home mount: not scanned
Bootloader: not scanned
Snapper: not scanned
Dependencies: not scanned
Pending backups: unknown
Rollback items: unknown
""".strip()

    def on_mount(self) -> None:
        self.update(self.DEFAULT_TEXT)


class ContentPanel(Static):
    """Main content area for the selected section."""

    current_section: reactive[str] = reactive("Dashboard")

    def watch_current_section(self, section: str) -> None:
        self.update(SECTION_CONTENT.get(section, section))


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
                    yield ContentPanel(id="content-panel")

        yield Footer()

    def on_mount(self) -> None:
        menu = self.query_one("#menu", ListView)
        menu.index = 0
        self._set_section("Dashboard")

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
        self._set_section(MENU_ITEMS[index])

    def action_refresh_summary(self) -> None:
        # Placeholder for the upcoming system scan integration.
        summary = self.query_one("#summary-box", SummaryBox)
        summary.update(SummaryBox.DEFAULT_TEXT)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id != "menu":
            return
        index = event.list_view.index or 0
        self._set_section(MENU_ITEMS[index])

    def watch_selected_section(self, section: str) -> None:
        content = self.query_one("#content-panel", ContentPanel)
        content.current_section = section

    def _set_section(self, section: str) -> None:
        self.selected_section = section


def main() -> None:
    DBLMApp().run()


if __name__ == "__main__":
    main()
