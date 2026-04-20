from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Static

from core.system import EnvironmentSnapshot
from ui.common import DBLMSectionScreen, safe_text


class ApplyScreen(DBLMSectionScreen):
    BINDINGS = [
        ("r", "refresh_apply", "Refresh"),
        ("l", "open_apply_logs", "Logs"),
        ("s", "start_apply_simulation", "Start"),
    ]

    def __init__(self, state_file: str | Path = "data/state.json") -> None:
        super().__init__(state_file=state_file)
        self.snapshot: EnvironmentSnapshot | None = None
        self.last_error: str | None = None

    def compose_body(self) -> ComposeResult:
        with Vertical(id="apply-root"):
            yield Static("[bold]Apply[/bold]", id="apply-title")
            yield Static(
                "Review execution readiness and recorded state before running destructive actions.",
                id="apply-subtitle",
            )

            with Horizontal(id="apply-actions"):
                yield Button("Refresh", id="refresh-apply", variant="primary")
                yield Button("Open Logs", id="open-apply-logs")
                yield Button("Start Apply Session", id="start-apply-session", variant="success")

            with Horizontal(id="apply-grid"):
                with Vertical(id="apply-left"):
                    yield Static("[bold]Execution readiness[/bold]", classes="panel-title")
                    yield Static(id="apply-readiness")

                    yield Static("[bold]Current plan status[/bold]", classes="panel-title")
                    yield Static(id="apply-plan-status")

                with Vertical(id="apply-right"):
                    yield Static("[bold]Recorded state[/bold]", classes="panel-title")
                    yield Static(id="apply-state")

                    yield Static("[bold]Execution log preview[/bold]", classes="panel-title")
                    yield Static(id="apply-log-preview")

            yield Static("[bold]Notes[/bold]", classes="panel-title")
            yield Static(id="apply-notes")

    def on_mount(self) -> None:
        self.log_screen_event("Mounted apply screen.")
        self.refresh_apply()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "refresh-apply":
            self.log_screen_event("Refresh requested from apply button.")
            self.refresh_apply()
        elif event.button.id == "open-apply-logs":
            self.action_open_apply_logs()
        elif event.button.id == "start-apply-session":
            self.action_start_apply_simulation()

    def action_refresh_apply(self) -> None:
        self.log_screen_event("Refresh requested from apply shortcut.")
        self.refresh_apply()

    def action_open_apply_logs(self) -> None:
        self.log_screen_event("Operation logs requested from apply screen.")
        app = getattr(self, "app", None)
        if app is not None and hasattr(app, "open_operation_logs"):
            app.open_operation_logs("Apply plan")

    def action_start_apply_simulation(self) -> None:
        """
        Start an installer-style simulated apply session.

        This prepares the UX and logging pipeline for the real execution engine
        that will be wired in later phases.
        """
        self.log_screen_event("Apply simulation requested.")
        app = getattr(self, "app", None)
        if app is None:
            return

        latest_run = self.state_manager.get_latest_run()
        summary = self.state_manager.summarize()
        snapshot = self.snapshot

        if hasattr(app, "start_operation_log"):
            app.start_operation_log("Apply plan")

        if hasattr(app, "append_operation_log"):
            app.append_operation_log("Preparing execution session.", level="info", source="apply")
            app.append_operation_log(
                f"Root filesystem detected: {safe_text(snapshot.root_fs.fstype) if snapshot else 'unknown'}",
                level="info",
                source="apply",
            )
            app.append_operation_log(
                f"Required dependencies OK: {'yes' if snapshot and snapshot.dependencies.required_ok else 'no'}",
                level="info",
                source="apply",
            )
            app.append_operation_log(
                f"Warnings detected: {len(snapshot.warnings) if snapshot else 0}",
                level="info",
                source="apply",
            )
            app.append_operation_log(
                f"Recorded runs: {summary.get('runs_total', 0)} | "
                f"Recorded backups: {summary.get('backups_total', 0)}",
                level="info",
                source="apply",
            )

            if latest_run is None:
                app.append_operation_log(
                    "No recorded run exists yet. Execution is limited to dry session setup.",
                    level="warning",
                    source="planner",
                )
            else:
                app.append_operation_log(
                    f"Latest run: {latest_run.run_id}",
                    level="info",
                    source="planner",
                )
                app.append_operation_log(
                    f"Latest run status: {latest_run.status}",
                    level="info",
                    source="planner",
                )
                app.append_operation_log(
                    f"Recorded actions in latest run: {len(latest_run.actions)}",
                    level="info",
                    source="planner",
                )
                for action in latest_run.actions[:20]:
                    app.append_operation_log(
                        f"Planned target={action.target} subvolume={action.subvolume or 'n/a'} "
                        f"status={action.status}",
                        level="info",
                        source="planner",
                    )

            if snapshot is None:
                app.append_operation_log(
                    "Environment snapshot is unavailable.",
                    level="error",
                    source="apply",
                )
            elif snapshot.root_fs.fstype != "btrfs":
                app.append_operation_log(
                    "Execution blocked: root filesystem is not Btrfs.",
                    level="error",
                    source="validator",
                )
            elif not snapshot.dependencies.required_ok:
                missing = ", ".join(snapshot.dependencies.missing_required) or "unknown"
                app.append_operation_log(
                    f"Execution blocked: missing required commands: {missing}",
                    level="error",
                    source="validator",
                )
            elif not snapshot.is_root:
                app.append_operation_log(
                    "Execution blocked: application is not running as root.",
                    level="error",
                    source="validator",
                )
            else:
                app.append_operation_log(
                    "Environment validation passed.",
                    level="info",
                    source="validator",
                )
                app.append_operation_log(
                    "This phase is currently running in installer-style simulation mode only.",
                    level="warning",
                    source="apply",
                )
                app.append_operation_log(
                    "Real filesystem operations will be connected in the next step.",
                    level="info",
                    source="apply",
                )

        if hasattr(app, "finish_operation_log"):
            ready = bool(
                snapshot
                and snapshot.root_fs.fstype == "btrfs"
                and snapshot.dependencies.required_ok
                and snapshot.is_root
            )
            app.finish_operation_log(
                success=ready,
                message=(
                    "Apply simulation completed. System is eligible for real execution wiring."
                    if ready
                    else "Apply simulation completed. Blocking conditions were detected."
                ),
            )

        if hasattr(app, "open_operation_logs"):
            app.open_operation_logs("Apply plan")

    def refresh_apply(self) -> None:
        try:
            self.snapshot = self.refresh_environment()
            self.last_error = None
            self.log_screen_event("Apply environment refresh completed.")
        except Exception as exc:  # pragma: no cover
            self.snapshot = None
            self.last_error = str(exc)
            self.log_screen_error(f"Apply refresh failed: {exc}")

        self._render()

    def _render(self) -> None:
        readiness_box = self.query_one("#apply-readiness", Static)
        plan_box = self.query_one("#apply-plan-status", Static)
        state_box = self.query_one("#apply-state", Static)
        log_box = self.query_one("#apply-log-preview", Static)
        notes_box = self.query_one("#apply-notes", Static)

        if self.snapshot is None:
            error = safe_text(self.last_error)
            readiness_box.update(
                f"[bold]Execution readiness[/bold]\n\nEnvironment scan failed.\n\nError: {error}"
            )
            plan_box.update("No execution plan data available.")
            state_box.update("No state data available.")
            log_box.update("No log data available.")
            notes_box.update("Refresh the screen after fixing the environment issue.")
            return

        summary = self.state_manager.summarize()
        latest_run = self.state_manager.get_latest_run()

        self.log_screen_event(
            "Rendering apply data "
            f"(latest_run={'yes' if latest_run is not None else 'no'}, "
            f"actions={len(latest_run.actions) if latest_run else 0}, "
            f"warnings={len(self.snapshot.warnings)}, "
            f"backups={summary.get('backups_total', 0)})."
        )

        readiness_box.update(self._build_readiness_text())
        plan_box.update(self._build_plan_text(latest_run))
        state_box.update(self._build_state_text(summary, latest_run))
        log_box.update(self._build_log_preview_text(latest_run))
        notes_box.update(self._build_notes_text(latest_run))

    def _build_readiness_text(self) -> str:
        snapshot = self.snapshot
        assert snapshot is not None

        blockers: list[str] = []
        if snapshot.root_fs.fstype != "btrfs":
            blockers.append("root is not Btrfs")
        if not snapshot.dependencies.required_ok:
            blockers.append("missing required commands")
        if not snapshot.is_root:
            blockers.append("application is not running as root")

        return (
            "[bold]Execution readiness[/bold]\n\n"
            f"Root filesystem: {safe_text(snapshot.root_fs.fstype)}\n"
            f"Root subvolume: {safe_text(snapshot.root_fs.subvol)}\n"
            f"Running as root: {'yes' if snapshot.is_root else 'no'}\n"
            f"Required dependencies OK: {'yes' if snapshot.dependencies.required_ok else 'no'}\n"
            f"Warnings detected: {len(snapshot.warnings)}\n\n"
            f"Blockers: {', '.join(blockers) if blockers else 'none'}"
        )

    def _build_plan_text(self, latest_run) -> str:
        if latest_run is None:
            return (
                "[bold]Current plan status[/bold]\n\n"
                "No recorded plan or execution run exists yet."
            )

        return (
            "[bold]Current plan status[/bold]\n\n"
            f"Latest run id: {latest_run.run_id}\n"
            f"Created at: {latest_run.created_at}\n"
            f"Status: {latest_run.status}\n"
            f"Recorded actions: {len(latest_run.actions)}\n"
            f"Warnings: {len(latest_run.warnings)}\n"
            f"Notes: {safe_text(latest_run.notes, 'none')}"
        )

    def _build_state_text(self, summary: dict[str, object], latest_run) -> str:
        return (
            "[bold]Recorded state[/bold]\n\n"
            f"Runs total: {summary.get('runs_total', 0)}\n"
            f"Backups total: {summary.get('backups_total', 0)}\n"
            f"Available backups: {summary.get('backups_available', 0)}\n"
            f"Restorable backups: {summary.get('backups_restorable', 0)}\n"
            f"Deleted backups: {summary.get('backups_deleted', 0)}\n\n"
            f"Latest run: {safe_text(summary.get('latest_run_id'))}\n"
            f"Latest run present: {'yes' if latest_run is not None else 'no'}"
        )

    def _build_log_preview_text(self, latest_run) -> str:
        app = getattr(self, "app", None)
        if app is not None and hasattr(app, "get_operation_log_entries"):
            operation_lines = app.get_operation_log_entries(limit=8)
            if operation_lines:
                return "[bold]Execution log preview[/bold]\n\n" + "\n".join(operation_lines)

        if latest_run is None or not latest_run.actions:
            return "[bold]Execution log preview[/bold]\n\nNo actions recorded yet."

        lines = [
            f"- {action.target} -> {action.subvolume or 'n/a'} [status={action.status}]"
            for action in latest_run.actions[-8:]
        ]
        return "[bold]Execution log preview[/bold]\n\n" + "\n".join(lines)

    def _build_notes_text(self, latest_run) -> str:
        snapshot = self.snapshot
        assert snapshot is not None

        notes: list[str] = []
        if not snapshot.is_root:
            notes.append("- DBLM must run as root before real apply actions are enabled.")
        if snapshot.root_fs.fstype != "btrfs":
            notes.append("- Root filesystem must be Btrfs before any layout changes are applied.")
        if not snapshot.dependencies.required_ok:
            notes.append("- Install missing required tools before applying changes.")
        if latest_run is None:
            notes.append("- No run has been recorded yet. Planning should happen before apply.")
        if latest_run is not None and latest_run.status == "failed":
            notes.append("- The latest run failed and should be reviewed before retrying.")
        notes.append("- Use 'Start Apply Session' to open installer-style operation logs.")
        if not notes:
            notes.append("- Environment looks suitable for wiring the real execution pipeline.")

        return "\n".join(notes)
