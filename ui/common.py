from __future__ import annotations

from pathlib import Path

from textual.screen import Screen

from core.state import StateManager
from core.system import EnvironmentSnapshot, scan_environment


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
    """

    def __init__(self, state_file: str | Path = "data/state.json") -> None:
        super().__init__()
        self._state_file = Path(state_file)
        self._fallback_state_manager: StateManager | None = None

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
