from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import Button, ListItem, ListView, Static

from core.profiles import (
    SubvolumeTarget,
    default_targets,
    filter_targets_for_home_support,
    get_profile,
    group_targets_by_scope,
    list_profiles,
    list_targets,
    resolve_profile_targets,
)
from core.system import EnvironmentSnapshot
from ui.common import DBLMSectionScreen, safe_text, yes_no


class SubvolumeScreen(DBLMSectionScreen):
    """Subvolume planning screen."""

    BINDINGS = [
        ("r", "refresh", "Refresh"),
        ("a", "mark_default", "Mark defaults"),
        ("c", "clear_selection", "Clear"),
    ]

    selected_profile: reactive[str] = reactive("custom")
    selected_target_key: reactive[str | None] = reactive(None)

    def __init__(self, state_file: str | Path = "data/state.json") -> None:
        super().__init__(state_file=state_file)
        self.snapshot: EnvironmentSnapshot | None = None
        self.last_error: str | None = None
        self.selected_keys: set[str] = set()

    def compose_body(self) -> ComposeResult:
        with Vertical(id="subvolumes-root"):
            yield Static("[bold]Subvolumes[/bold]", id="subvolumes-title")
            yield Static(
                "Choose a profile or select targets individually.",
                id="subvolumes-subtitle",
            )

            with Horizontal(id="subvolumes-actions"):
                yield Button("Refresh", id="refresh-subvolumes", variant="primary")
                yield Button("Mark defaults", id="mark-defaults")
                yield Button("Clear selection", id="clear-selection")

            with Horizontal(id="subvolumes-layout"):
                with Vertical(id="subvolumes-left"):
                    yield Static("[bold]Profiles[/bold]", classes="panel-title")
                    yield ListView(id="profile-list")

                    yield Static("[bold]Targets[/bold]", classes="panel-title")
                    yield ListView(id="target-list")

                with Vertical(id="subvolumes-right"):
                    yield Static("[bold]Target details[/bold]", classes="panel-title")
                    yield Static(id="target-details")

                    yield Static("[bold]Selection summary[/bold]", classes="panel-title")
                    yield Static(id="selection-summary")

    def on_mount(self) -> None:
        self._load_profiles()
        self.refresh_data()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "refresh-subvolumes":
            self.refresh_data()
        elif button_id == "mark-defaults":
            self.action_mark_default()
        elif button_id == "clear-selection":
            self.action_clear_selection()

    def action_refresh(self) -> None:
        self.refresh_data()

    def action_mark_default(self) -> None:
        include_home = self._home_support_enabled()
        defaults = default_targets(include_home=include_home)
        defaults = filter_targets_for_home_support(
            defaults,
            home_is_btrfs=include_home,
        )
        self.selected_keys = {target.key for target in defaults}
        self.selected_profile = "custom"
        self._render_targets()
        self._render_selected_target()
        self._render_summary()

    def action_clear_selection(self) -> None:
        self.selected_keys.clear()
        self.selected_profile = "custom"
        self._render_targets()
        self._render_selected_target()
        self._render_summary()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id == "profile-list":
            self._apply_profile_from_list(event.list_view.index or 0)
            return

        if event.list_view.id == "target-list":
            self._toggle_target_from_list(event.list_view.index or 0)
            return

    def refresh_data(self) -> None:
        try:
            self.snapshot = self.get_environment(force=True)
            self.last_error = None
        except Exception as exc:  # pragma: no cover - defensive UI path
            self.snapshot = None
            self.last_error = str(exc)

        self._render_profiles()
        self._render_targets()
        self._render_selected_target()
        self._render_summary()

    def _load_profiles(self) -> None:
        profile_list = self.query_one("#profile-list", ListView)
        profile_list.clear()

        profile_list.append(ListItem(Static("Custom")))
        for profile in list_profiles():
            profile_list.append(ListItem(Static(profile.name)))

        profile_list.index = 0

    def _render_profiles(self) -> None:
        profile_list = self.query_one("#profile-list", ListView)
        if profile_list.index is None:
            profile_list.index = 0

    def _render_targets(self) -> None:
        target_list = self.query_one("#target-list", ListView)
        target_list.clear()

        targets = self._available_targets()
        if not targets:
            target_list.append(ListItem(Static("No targets available")))
            self.selected_target_key = None
            return

        for target in targets:
            marker = "[x]" if target.key in self.selected_keys else "[ ]"
            scope = "home" if target.scope == "home" else "system"
            target_list.append(ListItem(Static(f"{marker} {target.path} ({scope})")))

        if self.selected_target_key not in {item.key for item in targets}:
            self.selected_target_key = targets[0].key

        if target_list.index is None:
            target_list.index = 0

    def _render_selected_target(self) -> None:
        details = self.query_one("#target-details", Static)
        target = self._current_target()

        if self.snapshot is None:
            details.update(
                "[bold]Status[/bold]\n\n"
                f"Unable to inspect system.\n\nError: {safe_text(self.last_error)}"
            )
            return

        if target is None:
            details.update("[bold]Status[/bold]\n\nNo target selected.")
            return

        home_supported = self._home_support_enabled()
        suggested_name = target.suggested_name(flat_layout=True)

        availability = "available"
        if target.requires_btrfs_home and not home_supported:
            availability = "unavailable: /home is not Btrfs-capable"

        selected = target.key in self.selected_keys
        current_path_exists = Path(target.path).exists()
        current_scope = "home filesystem" if target.scope == "home" else "system filesystem"

        details.update(
            "[bold]Target details[/bold]\n\n"
            f"Path: {target.path}\n"
            f"Key: {target.key}\n"
            f"Scope: {current_scope}\n"
            f"Description: {target.description}\n"
            f"Suggested subvolume name: {suggested_name}\n"
            f"Layout style: flat\n"
            f"Selected: {yes_no(selected)}\n"
            f"Path exists now: {yes_no(current_path_exists)}\n"
            f"Marked risky: {yes_no(target.risky)}\n"
            f"Requires Btrfs /home: {yes_no(target.requires_btrfs_home)}\n"
            f"Availability: {availability}"
        )

    def _render_summary(self) -> None:
        summary = self.query_one("#selection-summary", Static)

        if self.snapshot is None:
            summary.update("[bold]Selection[/bold]\n\nNo environment data available.")
            return

        selected_targets = [
            target for target in self._available_targets()
            if target.key in self.selected_keys
        ]
        grouped = group_targets_by_scope(selected_targets)

        profile_name = "Custom"
        if self.selected_profile != "custom":
            profile_name = get_profile(self.selected_profile).name

        home = self.snapshot.home_fs
        summary.update(
            "[bold]Selection summary[/bold]\n\n"
            f"Profile: {profile_name}\n"
            f"Selected targets: {len(selected_targets)}\n"
            f"System targets: {len(grouped.get('system', []))}\n"
            f"Home targets: {len(grouped.get('home', []))}\n\n"
            f"/home supports subvolumes: {yes_no(home.home_supports_subvolumes)}\n"
            f"/home summary: {home.display_name}\n\n"
            "Planned target paths:\n"
            + (
                "\n".join(f"- {target.path}" for target in selected_targets)
                if selected_targets
                else "- none selected"
            )
        )

    def _apply_profile_from_list(self, index: int) -> None:
        if index == 0:
            self.selected_profile = "custom"
            self._render_summary()
            return

        profiles = list_profiles()
        profile = profiles[index - 1]
        include_home = self._home_support_enabled()
        targets = resolve_profile_targets(profile.key, include_home=include_home)
        targets = filter_targets_for_home_support(
            targets,
            home_is_btrfs=include_home,
        )

        self.selected_profile = profile.key
        self.selected_keys = {target.key for target in targets}
        self._render_targets()
        self._render_selected_target()
        self._render_summary()

    def _toggle_target_from_list(self, index: int) -> None:
        targets = self._available_targets()
        if not targets or index >= len(targets):
            return

        target = targets[index]
        self.selected_target_key = target.key
        self.selected_profile = "custom"

        if target.requires_btrfs_home and not self._home_support_enabled():
            self._render_selected_target()
            self._render_summary()
            return

        if target.key in self.selected_keys:
            self.selected_keys.remove(target.key)
        else:
            self.selected_keys.add(target.key)

        self._render_targets()
        self._render_selected_target()
        self._render_summary()

    def _available_targets(self) -> list[SubvolumeTarget]:
        include_home = self._home_support_enabled()
        targets = list_targets(include_home=include_home)
        return filter_targets_for_home_support(
            targets,
            home_is_btrfs=include_home,
        )

    def _home_support_enabled(self) -> bool:
        return bool(self.snapshot and self.snapshot.home_fs.home_supports_subvolumes)

    def _current_target(self) -> SubvolumeTarget | None:
        targets = self._available_targets()
        if not targets:
            return None

        if self.selected_target_key is None:
            return targets[0]

        for target in targets:
            if target.key == self.selected_target_key:
                return target

        return targets[0]
