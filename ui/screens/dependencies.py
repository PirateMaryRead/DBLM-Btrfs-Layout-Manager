from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Static

from core.packages import (
    build_feature_requirements,
    build_install_plan,
    check_packages,
    get_apt_status,
    summarize_package_checks,
)
from core.system import EnvironmentSnapshot
from ui.common import DBLMScreen, safe_text, yes_no


class DependenciesScreen(DBLMScreen):
    """Dependency inspection screen for DBLM."""

    BINDINGS = [("r", "refresh_dependencies", "Refresh")]

    def __init__(self, state_file: str | Path = "data/state.json") -> None:
        super().__init__()
        self.snapshot: EnvironmentSnapshot | None = None
        self.last_error: str | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="dependencies-root"):
            yield Static("[bold]Dependencies[/bold]", id="dependencies-title")
            yield Static(
                "Inspect required and optional packages for DBLM features.",
                id="dependencies-subtitle",
            )

            with Horizontal(id="dependencies-actions"):
                yield Button("Refresh", id="refresh-dependencies", variant="primary")

            with Horizontal(id="dependencies-grid"):
                with Vertical(id="dependencies-left"):
                    yield Static("[bold]APT status[/bold]", classes="panel-title")
                    yield Static(id="dependencies-apt")

                    yield Static("[bold]Core requirements[/bold]", classes="panel-title")
                    yield Static(id="dependencies-core")

                with Vertical(id="dependencies-right"):
                    yield Static("[bold]Feature packages[/bold]", classes="panel-title")
                    yield Static(id="dependencies-features")

                    yield Static("[bold]Install plan[/bold]", classes="panel-title")
                    yield Static(id="dependencies-plan")

            yield Static("[bold]Notes[/bold]", classes="panel-title")
            yield Static(id="dependencies-notes")

    def on_mount(self) -> None:
        self.refresh_dependencies()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "refresh-dependencies":
            self.refresh_dependencies()

    def action_refresh_dependencies(self) -> None:
        self.refresh_dependencies()

    def refresh_dependencies(self) -> None:
        try:
            self.snapshot = self.get_environment(force=True)
            self.last_error = None
        except Exception as exc:  # pragma: no cover
            self.snapshot = None
            self.last_error = str(exc)

        self._render()

    def _render(self) -> None:
        apt_box = self.query_one("#dependencies-apt", Static)
        core_box = self.query_one("#dependencies-core", Static)
        features_box = self.query_one("#dependencies-features", Static)
        plan_box = self.query_one("#dependencies-plan", Static)
        notes_box = self.query_one("#dependencies-notes", Static)

        if self.snapshot is None:
            error = safe_text(self.last_error)
            apt_box.update(f"[bold]APT status[/bold]\n\nEnvironment scan failed.\n\nError: {error}")
            core_box.update("No dependency data available.")
            features_box.update("No feature data available.")
            plan_box.update("No install plan available.")
            notes_box.update("Refresh the screen after fixing the environment issue.")
            return

        apt_status = get_apt_status()

        core_requirements = build_feature_requirements()
        core_checks = check_packages(core_requirements)
        core_summary = summarize_package_checks(core_checks)

        feature_requirements = build_feature_requirements(
            include_snapper=True,
            include_grub=True,
            include_systemd_boot=True,
            include_optional=True,
        )
        feature_checks = check_packages(feature_requirements)
        feature_summary = summarize_package_checks(feature_checks)
        install_plan = build_install_plan(feature_requirements)

        apt_box.update(self._build_apt_text(apt_status))
        core_box.update(self._build_core_text(core_summary))
        features_box.update(self._build_feature_text(feature_summary))
        plan_box.update(self._build_plan_text(install_plan))
        notes_box.update(self._build_notes_text(apt_status, core_summary, feature_summary))

    def _build_apt_text(self, apt_status) -> str:
        return (
            "[bold]APT status[/bold]\n\n"
            f"apt available: {yes_no(apt_status.has_apt)}\n"
            f"apt-get available: {yes_no(apt_status.has_apt_get)}\n"
            f"dpkg-query available: {yes_no(apt_status.has_dpkg_query)}\n"
            f"usable package tooling: {yes_no(apt_status.usable)}\n"
            f"can install packages: {yes_no(apt_status.can_install)}"
        )

    def _build_core_text(self, summary: dict[str, list[str]]) -> str:
        installed = summary.get("installed", [])
        missing_required = summary.get("missing_required", [])

        return (
            "[bold]Core requirements[/bold]\n\n"
            f"Installed: {', '.join(installed) if installed else 'none'}\n"
            f"Missing required: {', '.join(missing_required) if missing_required else 'none'}"
        )

    def _build_feature_text(self, summary: dict[str, list[str]]) -> str:
        installed = summary.get("installed", [])
        missing_required = summary.get("missing_required", [])
        missing_optional = summary.get("missing_optional", [])

        return (
            "[bold]Feature packages[/bold]\n\n"
            f"Installed packages: {', '.join(installed) if installed else 'none'}\n"
            f"Missing required packages: {', '.join(missing_required) if missing_required else 'none'}\n"
            f"Missing optional packages: {', '.join(missing_optional) if missing_optional else 'none'}"
        )

    def _build_plan_text(self, install_plan) -> str:
        return (
            "[bold]Install plan[/bold]\n\n"
            f"Already installed: {', '.join(install_plan.already_installed) if install_plan.already_installed else 'none'}\n"
            f"To install: {', '.join(install_plan.to_install) if install_plan.to_install else 'none'}\n"
            f"Missing APT support: {yes_no(install_plan.missing_apt_support)}\n"
            f"Plan empty: {yes_no(install_plan.is_empty)}"
        )

    def _build_notes_text(
        self,
        apt_status,
        core_summary: dict[str, list[str]],
        feature_summary: dict[str, list[str]],
    ) -> str:
        notes: list[str] = []

        if not apt_status.usable:
            notes.append("- APT tooling is incomplete; automatic package installation will not work.")

        if core_summary.get("missing_required"):
            notes.append("- Install missing core packages before applying filesystem changes.")

        if feature_summary.get("missing_optional"):
            notes.append("- Optional feature packages can be installed later when those features are enabled.")

        if not notes:
            notes.append("- Dependency checks look good for the current environment.")

        return "\n".join(notes)
