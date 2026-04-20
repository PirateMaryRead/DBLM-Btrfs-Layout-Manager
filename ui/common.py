from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from core.logging import get_logger, log_exception
from core.state import StateManager
from core.system import EnvironmentSnapshot, scan_environment


DEFAULT_UI_STATE_FILE = Path(__file__).resolve().parent.parent / "data" / "state.json"


def safe_text(value: object | None, fallback: str = "unknown") -> str:
    """Return a readable string for UI rendering."""
    if value is None:
        return fallback
    text = str(value).strip()
    return text if text else fallback


def yes_no(value: bool) -> str:
    """Render booleans consistently in the UI."""
    return "yes" if value else "no"


class DBLMScreen(Screen[None]):
    """
    Shared screen base for DBLM.

    It centralizes:
    - access to the app-level StateManager when available
    - access to cached environment data when available
    - a safe fallback for standalone screen usage
    - a screen-specific logger
    """

    def __init__(self, state_file: str | Path = DEFAULT_UI_STATE_FILE) -> None:
        super().__init__()
        self._state_file = Path(state_file)
        self._fallback_state_manager: StateManager | None = None
        self.logger = get_logger(f"ui.{self.__class__.__name__.lower()}")

    @property
    def state_manager(self) -> StateManager:
        """
        Return the shared StateManager from the app when available.

        Falls back to a local StateManager when the screen is used outside the
        main DBLM app context.
        """
        app = getattr(self, "app", None)
        if app is not None and hasattr(app, "state_manager"):
            return app.state_manager  # type: ignore[return-value]

        if self._fallback_state_manager is None:
            self._fallback_state_manager = StateManager(self._state_file)
        return self._fallback_state_manager

    def get_environment(self, *, force: bool = False) -> EnvironmentSnapshot:
        """
        Return the current environment snapshot.

        Uses app-level caching when available. Falls back to a direct scan when
        the screen is running standalone.
        """
        app = getattr(self, "app", None)
        if app is not None and hasattr(app, "get_environment"):
            return app.get_environment(force=force)  # type: ignore[return-value]

        return scan_environment()

    def invalidate_environment_cache(self) -> None:
        """Ask the app to clear its cached environment snapshot when supported."""
        app = getattr(self, "app", None)
        if app is not None and hasattr(app, "invalidate_environment_cache"):
            app.invalidate_environment_cache()

    def refresh_environment(self) -> EnvironmentSnapshot:
        """Force-refresh and return the environment snapshot, logging the event."""
        self.log_screen_event("Refreshing environment.")
        return self.get_environment(force=True)

    def log_screen_event(self, message: str) -> None:
        """Write a screen-level log entry."""
        self.logger.info(message)

    def log_screen_error(self, message: str) -> None:
        """Log an exception-oriented message for this screen."""
        log_exception(f"{self.__class__.__name__}: {message}", logger_name="ui.errors")


class DBLMSectionScreen(DBLMScreen):
    """
    Base class for all visible DBLM sections.

    It standardizes:
    - Header on every screen
    - Footer on every screen
    - a compose_body() pattern so content stays focused on the section itself
    """

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield from self.compose_body()
        yield Footer()

    def compose_body(self) -> ComposeResult:
        """Subclasses must provide the section body."""
        yield Static("Section body not implemented.")

    def on_mount(self) -> None:
        self.log_screen_event("Mounted section screen.")


class HelpScreen(DBLMSectionScreen):
    """Keyboard help screen for DBLM."""

    def compose_body(self) -> ComposeResult:
        with Vertical(id="help-root"):
            yield Static("[bold]Help[/bold]", id="help-title")
            yield Static(
                "Keyboard shortcuts available across DBLM screens.",
                id="help-subtitle",
            )
            yield Static(
                "[bold]Function keys[/bold]\n\n"
                "F1  Dashboard\n"
                "F2  Dependencies\n"
                "F3  Subvolumes\n"
                "F4  Snapper\n"
                "F5  Boot\n"
                "F6  Plan\n"
                "F7  Backups\n"
                "F8  Logs\n\n"
                "[bold]Additional shortcuts[/bold]\n\n"
                "H   Help\n"
                "A   Apply\n"
                "V   Revert\n"
                "M   Main menu\n"
                "B   Back\n"
                "R   Refresh current screen\n"
                "Q   Quit\n\n"
                "[bold]Logs[/bold]\n\n"
                "- The Logs screen shows application logs from the in-memory buffer.\n"
                "- Future apply/revert operations can reuse the same screen in operation mode.\n\n"
                "[bold]Notes[/bold]\n\n"
                "- Function keys are reserved for the most frequently used sections.\n"
                "- Apply and Revert remain directly accessible with letter shortcuts.\n"
                "- The footer shows currently available bindings.",
                id="help-content",
            )
