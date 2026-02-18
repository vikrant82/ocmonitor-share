"""Live monitoring service for OpenCode Monitor."""

import time
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from ..config import ModelPricing, PathsConfig
from ..models.session import InteractionFile, SessionData, TokenUsage
from ..models.workflow import SessionWorkflow
from ..ui.dashboard import DashboardUI
from ..ui.tables import TableFormatter
from ..utils.data_loader import DataLoader
from ..utils.file_utils import FileProcessor
from ..utils.sqlite_utils import SQLiteProcessor
from .session_grouper import SessionGrouper


class WorkflowWrapper:
    """Wrapper for SQLite workflow data that mimics SessionWorkflow interface."""

    def __init__(
        self, workflow_dict: Dict[str, Any], pricing_data: Dict[str, ModelPricing]
    ):
        self.main_session: SessionData = workflow_dict["main_session"]
        self.sub_agents: List[SessionData] = workflow_dict["sub_agents"]
        self.all_sessions: List[SessionData] = workflow_dict["all_sessions"]
        self.project_name: str = workflow_dict["project_name"]
        self.display_title: str = workflow_dict["display_title"]
        self.session_count: int = workflow_dict["session_count"]
        self.sub_agent_count: int = workflow_dict["sub_agent_count"]
        self.has_sub_agents: bool = workflow_dict["has_sub_agents"]
        self.workflow_id: str = workflow_dict["workflow_id"]
        self._pricing_data = pricing_data

        # Calculate total tokens across all sessions
        self.total_tokens = TokenUsage()
        for session in self.all_sessions:
            tokens = session.total_tokens
            self.total_tokens.input += tokens.input
            self.total_tokens.output += tokens.output
            self.total_tokens.cache_write += tokens.cache_write
            self.total_tokens.cache_read += tokens.cache_read

        # Calculate time properties across all sessions
        start_times = []
        end_times = []
        for session in self.all_sessions:
            if session.start_time:
                start_times.append(session.start_time)
            if session.end_time:
                end_times.append(session.end_time)

        self.start_time: Optional[datetime] = min(start_times) if start_times else None
        self.end_time: Optional[datetime] = max(end_times) if end_times else None

        # Calculate duration
        if self.start_time and self.end_time:
            self.duration_ms: Optional[int] = int(
                (self.end_time - self.start_time).total_seconds() * 1000
            )
            self.duration_hours: float = self.duration_ms / (1000 * 60 * 60)
            self.duration_percentage: float = min(
                100.0, (self.duration_hours / 5.0) * 100
            )
        else:
            self.duration_ms = None
            self.duration_hours = 0.0
            self.duration_percentage = 0.0

    def calculate_total_cost(
        self, pricing_data: Optional[Dict[str, ModelPricing]] = None
    ) -> Decimal:
        """Calculate total cost across all sessions in workflow."""
        pricing = pricing_data or self._pricing_data
        total = Decimal("0.0")
        for session in self.all_sessions:
            total += session.calculate_total_cost(pricing)
        return total


class LiveMonitor:
    """Service for live monitoring of OpenCode sessions."""

    def __init__(
        self,
        pricing_data: Dict[str, ModelPricing],
        console: Optional[Console] = None,
        paths_config: Optional[PathsConfig] = None,
    ):
        """Initialize live monitor.

        Args:
            pricing_data: Model pricing information
            console: Rich console for output
            paths_config: Path configuration for resolving default storage paths
        """
        self.pricing_data = pricing_data
        self.console = console or Console()
        self.paths_config = paths_config
        self.dashboard_ui = DashboardUI(console)
        self.session_grouper = SessionGrouper()
        self._active_workflows: Dict[str, Any] = {}
        self._displayed_workflow_id: Optional[str] = None
        self._initialize_active_workflows()

    def _initialize_active_workflows(self):
        """Initialize tracking of active workflows from database."""
        db_path = SQLiteProcessor.find_database_path()
        if db_path:
            processor = SQLiteProcessor()
            workflows = processor.get_all_active_workflows(Path(db_path))
            for wf in workflows:
                wf_id = wf["workflow_id"]
                self._active_workflows[wf_id] = wf
            if self._active_workflows:
                most_recent = self._select_most_recent_workflow(
                    list(self._active_workflows.values())
                )
                self._displayed_workflow_id = most_recent["workflow_id"]

    def _get_tracked_workflow_ids(self) -> Set[str]:
        """Return set of tracked workflow IDs (for testing)."""
        return set(self._active_workflows.keys())

    def _get_displayed_workflow(self) -> Optional[Dict[str, Any]]:
        """Return the currently displayed workflow (for testing)."""
        if self._displayed_workflow_id:
            return self._active_workflows.get(self._displayed_workflow_id)
        return None

    def _refresh_active_workflows(self, db_path: str):
        """Refresh active workflows from database (for testing)."""
        processor = SQLiteProcessor()
        workflows = processor.get_all_active_workflows(Path(db_path))
        current_ids = set(self._active_workflows.keys())
        new_ids = {wf["workflow_id"] for wf in workflows}
        ended_ids = current_ids - new_ids
        for ended_id in ended_ids:
            wf = self._active_workflows.get(ended_id)
            if wf:
                main_session = wf.get("main_session")
                if main_session is not None:
                    end_time = getattr(main_session, "end_time", None)
                    if end_time is not None:
                        del self._active_workflows[ended_id]
        for wf in workflows:
            self._active_workflows[wf["workflow_id"]] = wf
        if self._active_workflows:
            most_recent = self._select_most_recent_workflow(
                list(self._active_workflows.values())
            )
            self._displayed_workflow_id = most_recent["workflow_id"]
        else:
            self._displayed_workflow_id = None

    def start_monitoring(self, base_path: str, refresh_interval: int = 5):
        """Start live monitoring of all active workflows (main session + sub-agents).

        Tracks all active (ongoing) workflows and displays the one with most recent activity.

        Args:
            base_path: Path to directory containing sessions
            refresh_interval: Update interval in seconds
        """
        try:
            sessions = FileProcessor.load_all_sessions(base_path, limit=50)
            if not sessions:
                self.console.print(
                    f"[status.error]No sessions found in {base_path}[/status.error]"
                )
                return

            workflows = self.session_grouper.group_sessions(sessions)
            if not workflows:
                self.console.print(f"[status.error]No workflows found[/status.error]")
                return

            active_workflows = [w for w in workflows if w.end_time is None]
            if not active_workflows:
                active_workflows = workflows[:1]

            active_workflows_dict: Dict[str, SessionWorkflow] = {
                w.workflow_id: w for w in active_workflows
            }
            tracked_session_ids = set()
            for w in active_workflows:
                tracked_session_ids.update(s.session_id for s in w.all_sessions)
            prev_tracked = tracked_session_ids.copy()

            current_workflow = self._select_most_recent_file_workflow(active_workflows)
            current_workflow_id = current_workflow.workflow_id

            self.console.print(
                f"[status.success]Starting live monitoring of workflow: {current_workflow.main_session.session_id}[/status.success]"
            )
            if current_workflow.has_sub_agents:
                self.console.print(
                    f"[status.info]Tracking {current_workflow.session_count} sessions (1 main + {current_workflow.sub_agent_count} sub-agents)[/status.info]"
                )
            if len(active_workflows_dict) > 1:
                self.console.print(
                    f"[status.info]Monitoring {len(active_workflows_dict)} active workflows[/status.info]"
                )
            self.console.print(
                f"[status.info]Update interval: {refresh_interval} seconds[/status.info]"
            )
            self.console.print("[dim]Press Ctrl+C to exit[/dim]\n")

            with Live(
                self._generate_workflow_dashboard(current_workflow),
                refresh_per_second=1 / refresh_interval,
                console=self.console,
            ) as live:
                while True:
                    sessions = FileProcessor.load_all_sessions(base_path, limit=50)
                    workflows = self.session_grouper.group_sessions(sessions)

                    if workflows:
                        new_active = [w for w in workflows if w.end_time is None]
                        if not new_active:
                            new_active = workflows[:1]

                        new_workflows_dict = {w.workflow_id: w for w in new_active}

                        new_ids = set(new_workflows_dict.keys()) - set(
                            active_workflows_dict.keys()
                        )
                        for wid in new_ids:
                            w = new_workflows_dict[wid]
                            self.console.print(
                                f"\n[status.warning]New workflow detected: {w.main_session.session_id}[/status.warning]"
                            )
                            if w.has_sub_agents:
                                self.console.print(
                                    f"[status.info]Tracking {w.session_count} sessions (1 main + {w.sub_agent_count} sub-agents)[/status.info]"
                                )

                        ended_ids = set(active_workflows_dict.keys()) - set(
                            new_workflows_dict.keys()
                        )
                        for wid in ended_ids:
                            self.console.print(
                                f"\n[status.info]Workflow ended: {wid}[/status.info]"
                            )

                        active_workflows_dict = new_workflows_dict
                        active_workflows = list(new_workflows_dict.values())

                        prev_tracked = tracked_session_ids.copy()
                        tracked_session_ids = set()
                        for w in active_workflows:
                            tracked_session_ids.update(
                                s.session_id for s in w.all_sessions
                            )

                        if active_workflows:
                            new_current = self._select_most_recent_file_workflow(
                                active_workflows
                            )
                            if new_current.workflow_id != current_workflow_id:
                                current_workflow_id = new_current.workflow_id
                                self.console.print(
                                    f"\n[status.info]Switched to workflow: {current_workflow_id}[/status.info]"
                                )
                            current_workflow = new_current

                    if current_workflow:
                        new_ids_set = set(
                            s.session_id for s in current_workflow.all_sessions
                        )
                        new_subs = new_ids_set - prev_tracked
                        if new_subs:
                            for sub_id in new_subs:
                                self.console.print(
                                    f"\n[status.info]New sub-agent detected: {sub_id}[/status.info]"
                                )

                    if current_workflow:
                        live.update(self._generate_workflow_dashboard(current_workflow))
                    time.sleep(refresh_interval)

        except KeyboardInterrupt:
            self.console.print(
                "\n[status.warning]Live monitoring stopped.[/status.warning]"
            )

    def _generate_dashboard(self, session: SessionData):
        """Generate dashboard layout for the session.

        Args:
            session: Session to monitor

        Returns:
            Rich layout for the dashboard
        """
        # Get the most recent file
        recent_file = None
        if session.files:
            recent_file = max(session.files, key=lambda f: f.modification_time)

        # Calculate output rate (tokens per second over last 5 minutes)
        output_rate = self._calculate_output_rate(session)

        # Get model pricing for quota and context window
        quota = None
        context_window = 200000  # Default

        if recent_file and recent_file.model_id in self.pricing_data:
            model_pricing = self.pricing_data[recent_file.model_id]
            quota = model_pricing.session_quota
            context_window = model_pricing.context_window

        return self.dashboard_ui.create_dashboard_layout(
            session=session,
            recent_file=recent_file,
            pricing_data=self.pricing_data,
            burn_rate=output_rate,
            quota=quota,
            context_window=context_window,
        )

    def _generate_workflow_dashboard(self, workflow: SessionWorkflow):
        """Generate dashboard layout for a workflow (main + sub-agents).

        Args:
            workflow: Workflow to monitor

        Returns:
            Rich layout for the dashboard
        """
        # Get all files from all sessions in the workflow
        all_files: List[InteractionFile] = []
        for session in workflow.all_sessions:
            all_files.extend(session.files)

        # Get the most recent file across all sessions
        recent_file = None
        if all_files:
            recent_file = max(all_files, key=lambda f: f.modification_time)

        # Calculate output rate across entire workflow
        output_rate = self._calculate_workflow_output_rate(workflow)

        # Get model pricing for quota and context window
        quota = None
        context_window = 200000  # Default

        if recent_file and recent_file.model_id in self.pricing_data:
            model_pricing = self.pricing_data[recent_file.model_id]
            quota = model_pricing.session_quota
            context_window = model_pricing.context_window

        # Create a combined session-like view for the dashboard
        # We'll pass workflow info to the dashboard UI
        return self.dashboard_ui.create_dashboard_layout(
            session=workflow.main_session,
            recent_file=recent_file,
            pricing_data=self.pricing_data,
            burn_rate=output_rate,
            quota=quota,
            context_window=context_window,
            workflow=workflow,  # Pass workflow for additional display
        )

    def _calculate_workflow_output_rate(self, workflow: SessionWorkflow) -> float:
        """Calculate output token rate across entire workflow.

        Args:
            workflow: Workflow containing all sessions

        Returns:
            Output tokens per second over the last 5 minutes
        """
        # Get all files from all sessions
        all_files: List[InteractionFile] = []
        for session in workflow.all_sessions:
            all_files.extend(session.files)

        if not all_files:
            return 0.0

        # Calculate the cutoff time (5 minutes ago)
        cutoff_time = datetime.now() - timedelta(minutes=5)

        # Filter interactions from the last 5 minutes
        recent_interactions = [
            f for f in all_files if f.modification_time >= cutoff_time
        ]

        if not recent_interactions:
            return 0.0

        # Sum output tokens from recent interactions
        total_output_tokens = sum(f.tokens.output for f in recent_interactions)

        if total_output_tokens == 0:
            return 0.0

        # Sum active processing time (duration_ms) from recent interactions
        total_duration_ms = 0
        for f in recent_interactions:
            if f.time_data and f.time_data.duration_ms:
                total_duration_ms += f.time_data.duration_ms

        # Convert to seconds
        total_duration_seconds = total_duration_ms / 1000

        if total_duration_seconds > 0:
            return total_output_tokens / total_duration_seconds

        return 0.0

    def _calculate_output_rate(self, session: SessionData) -> float:
        """Calculate output token rate over the last 5 minutes of activity.

        Args:
            session: SessionData object containing all interactions

        Returns:
            Output tokens per second over the last 5 minutes
        """
        if not session.files:
            return 0.0

        # Calculate the cutoff time (5 minutes ago)
        cutoff_time = datetime.now() - timedelta(minutes=5)

        # Filter interactions from the last 5 minutes
        recent_interactions = [
            f for f in session.files if f.modification_time >= cutoff_time
        ]

        if not recent_interactions:
            return 0.0

        # Sum output tokens from recent interactions
        total_output_tokens = sum(f.tokens.output for f in recent_interactions)

        # If no output tokens, return 0
        if total_output_tokens == 0:
            return 0.0

        # Sum active processing time (duration_ms) from recent interactions
        total_duration_ms = 0
        for f in recent_interactions:
            if f.time_data and f.time_data.duration_ms:
                total_duration_ms += f.time_data.duration_ms

        # Convert to seconds
        total_duration_seconds = total_duration_ms / 1000

        if total_duration_seconds > 0:
            return total_output_tokens / total_duration_seconds

        return 0.0

    def get_session_status(self, base_path: str) -> Dict[str, Any]:
        """Get current status of the most recent session.

        Args:
            base_path: Path to directory containing sessions

        Returns:
            Dictionary with session status information
        """
        recent_session = FileProcessor.get_most_recent_session(base_path)
        if not recent_session:
            return {"status": "no_sessions", "message": "No sessions found"}

        recent_file = None
        if recent_session.files:
            recent_file = max(recent_session.files, key=lambda f: f.modification_time)

        # Calculate how long ago the last activity was
        last_activity = None
        if recent_file:
            last_activity = time.time() - recent_file.modification_time.timestamp()

        # Determine activity status
        activity_status = "unknown"
        if last_activity is not None:
            if last_activity < 60:  # Less than 1 minute
                activity_status = "active"
            elif last_activity < 300:  # Less than 5 minutes
                activity_status = "recent"
            elif last_activity < 1800:  # Less than 30 minutes
                activity_status = "idle"
            else:
                activity_status = "inactive"

        return {
            "status": "found",
            "session_id": recent_session.session_id,
            "interaction_count": recent_session.interaction_count,
            "total_tokens": recent_session.total_tokens.total,
            "total_cost": float(recent_session.calculate_total_cost(self.pricing_data)),
            "models_used": recent_session.models_used,
            "last_activity_seconds": last_activity,
            "activity_status": activity_status,
            "output_rate": self._calculate_output_rate(recent_session),
            "recent_file": {
                "name": recent_file.file_name,
                "model": recent_file.model_id,
                "tokens": recent_file.tokens.total,
            }
            if recent_file
            else None,
        }

    def monitor_single_update(self, base_path: str) -> Optional[Dict[str, Any]]:
        """Get a single update of the monitoring data.

        Args:
            base_path: Path to directory containing sessions

        Returns:
            Monitoring data or None if no session found
        """
        recent_session = FileProcessor.get_most_recent_session(base_path)
        if not recent_session:
            return None

        recent_file = None
        if recent_session.files:
            recent_file = max(recent_session.files, key=lambda f: f.modification_time)

        return {
            "timestamp": time.time(),
            "session": {
                "id": recent_session.session_id,
                "interaction_count": recent_session.interaction_count,
                "total_tokens": recent_session.total_tokens.model_dump(),
                "total_cost": float(
                    recent_session.calculate_total_cost(self.pricing_data)
                ),
                "models_used": recent_session.models_used,
            },
            "recent_interaction": {
                "file_name": recent_file.file_name,
                "model_id": recent_file.model_id,
                "tokens": recent_file.tokens.model_dump(),
                "cost": float(recent_file.calculate_cost(self.pricing_data)),
                "modification_time": recent_file.modification_time.isoformat(),
            }
            if recent_file
            else None,
            "output_rate": self._calculate_output_rate(recent_session),
            "context_usage": self._calculate_context_usage(recent_file)
            if recent_file
            else None,
        }

    def _calculate_context_usage(
        self, interaction_file: InteractionFile
    ) -> Dict[str, Any]:
        """Calculate context window usage for an interaction.

        Args:
            interaction_file: Interaction file to analyze

        Returns:
            Context usage information
        """
        if interaction_file.model_id not in self.pricing_data:
            return {
                "context_size": 0,
                "context_window": 200000,
                "usage_percentage": 0.0,
            }

        model_pricing = self.pricing_data[interaction_file.model_id]
        context_window = model_pricing.context_window

        # Context size = input + cache read + cache write
        context_size = (
            interaction_file.tokens.input
            + interaction_file.tokens.cache_read
            + interaction_file.tokens.cache_write
        )

        usage_percentage = (
            (context_size / context_window) * 100 if context_window > 0 else 0
        )

        return {
            "context_size": context_size,
            "context_window": context_window,
            "usage_percentage": min(100.0, usage_percentage),
        }

    def start_sqlite_workflow_monitoring(self, refresh_interval: int = 5):
        """Start live monitoring of all active workflows from SQLite (v1.2.0+).

        Tracks all active (ongoing) workflows and displays the one with most recent activity.
        Shows the current workflow (main session + sub-agents) with detailed metrics.

        Args:
            refresh_interval: Update interval in seconds
        """
        try:
            # Check if SQLite is available
            db_path = SQLiteProcessor.find_database_path()
            if not db_path:
                self.console.print(
                    "[status.error]SQLite database not found.[/status.error]"
                )
                return

            # Load all active workflows
            active_workflows = SQLiteProcessor.get_all_active_workflows(db_path)
            if not active_workflows:
                # Fall back to most recent if no active workflows
                workflow = SQLiteProcessor.get_most_recent_workflow(db_path)
                if not workflow:
                    self.console.print(
                        "[status.error]No sessions found in database.[/status.error]"
                    )
                    return
                active_workflows = [workflow]

            # Track active workflows by workflow_id
            active_workflows_dict: Dict[str, Dict[str, Any]] = {
                w["workflow_id"]: w for w in active_workflows
            }
            tracked_session_ids = set()
            for w in active_workflows:
                tracked_session_ids.update(s.session_id for s in w["all_sessions"])

            # Get the workflow to display (most recently active)
            current_workflow = self._select_most_recent_workflow(active_workflows)
            current_workflow_id = current_workflow["workflow_id"]

            self.console.print(
                f"[status.success]Starting live monitoring of workflow: {current_workflow_id}[/status.success]"
            )
            if current_workflow["has_sub_agents"]:
                self.console.print(
                    f"[status.info]Tracking {current_workflow['session_count']} sessions (1 main + {current_workflow['sub_agent_count']} sub-agents)[/status.info]"
                )
            if len(active_workflows_dict) > 1:
                self.console.print(
                    f"[status.info]Monitoring {len(active_workflows_dict)} active workflows[/status.info]"
                )
            self.console.print(
                f"[status.info]Update interval: {refresh_interval} seconds[/status.info]"
            )
            self.console.print("[dim]Press Ctrl+C to exit[/dim]\n")

            # Start live monitoring
            with Live(
                self._generate_sqlite_workflow_dashboard(current_workflow),
                refresh_per_second=1 / refresh_interval,
                console=self.console,
            ) as live:
                while True:
                    # Reload all active workflows from SQLite
                    new_active_workflows = SQLiteProcessor.get_all_active_workflows(
                        db_path
                    )

                    if new_active_workflows:
                        new_workflows_dict = {
                            w["workflow_id"]: w for w in new_active_workflows
                        }

                        # Check for new workflows
                        new_ids = set(new_workflows_dict.keys()) - set(
                            active_workflows_dict.keys()
                        )
                        for wid in new_ids:
                            self.console.print(
                                f"\n[status.warning]New workflow detected: {wid}[/status.warning]"
                            )
                            w = new_workflows_dict[wid]
                            if w["has_sub_agents"]:
                                self.console.print(
                                    f"[status.info]Tracking {w['session_count']} sessions (1 main + {w['sub_agent_count']} sub-agents)[/status.info]"
                                )

                        # Check for ended workflows
                        ended_ids = set(active_workflows_dict.keys()) - set(
                            new_workflows_dict.keys()
                        )
                        for wid in ended_ids:
                            self.console.print(
                                f"\n[status.info]Workflow ended: {wid}[/status.info]"
                            )

                        # Update active workflows
                        active_workflows_dict = new_workflows_dict
                        active_workflows = list(new_workflows_dict.values())

                        # Update tracked session ids
                        tracked_session_ids = set()
                        for w in active_workflows:
                            tracked_session_ids.update(
                                s.session_id for s in w["all_sessions"]
                            )

                        # Select the workflow to display (most recently active)
                        if active_workflows:
                            new_current = self._select_most_recent_workflow(
                                active_workflows
                            )
                            if new_current["workflow_id"] != current_workflow_id:
                                current_workflow_id = new_current["workflow_id"]
                                self.console.print(
                                    f"\n[status.info]Switched to workflow: {current_workflow_id}[/status.info]"
                                )
                            current_workflow = new_current

                    # Check for new sub-agents in current workflow
                    if current_workflow:
                        new_ids_set = set(
                            s.session_id for s in current_workflow["all_sessions"]
                        )
                        new_subs = new_ids_set - tracked_session_ids
                        if new_subs:
                            for sub_id in new_subs:
                                self.console.print(
                                    f"\n[status.info]New sub-agent detected: {sub_id}[/status.info]"
                                )
                            tracked_session_ids.update(new_ids_set)

                    # Update dashboard
                    if current_workflow:
                        live.update(
                            self._generate_sqlite_workflow_dashboard(current_workflow)
                        )
                    time.sleep(refresh_interval)

        except KeyboardInterrupt:
            self.console.print(
                "\n[status.warning]Live monitoring stopped.[/status.warning]"
            )

    def _select_most_recent_workflow(
        self, workflows: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Select the workflow with most recent activity.

        Args:
            workflows: List of workflow dicts

        Returns:
            The workflow with the most recent file modification
        """
        if not workflows:
            raise ValueError("No workflows to select from")
        if len(workflows) == 1:
            return workflows[0]

        def get_latest_activity(workflow: Dict[str, Any]) -> float:
            latest = 0.0
            has_file_activity = False
            for session in workflow["all_sessions"]:
                for f in session.files:
                    if f.time_data and f.time_data.created:
                        latest = max(latest, f.time_data.created)
                        has_file_activity = True
            if not has_file_activity and workflow.get("main_session"):
                start_time = workflow["main_session"].start_time
                if start_time:
                    try:
                        ts = start_time.timestamp()
                        latest = float(ts)
                    except (AttributeError, TypeError, ValueError):
                        if type(start_time) in (int, float):
                            latest = float(start_time)
                        else:
                            latest = 0.0
            return latest

        return max(workflows, key=get_latest_activity)

    def _select_most_recent_file_workflow(
        self, workflows: List[SessionWorkflow]
    ) -> SessionWorkflow:
        """Select the file-based workflow with most recent activity.

        Args:
            workflows: List of SessionWorkflow objects

        Returns:
            The workflow with the most recent file modification
        """
        if not workflows:
            raise ValueError("No workflows to select from")
        if len(workflows) == 1:
            return workflows[0]

        def get_latest_activity(workflow: SessionWorkflow) -> float:
            latest = 0.0
            for session in workflow.all_sessions:
                for f in session.files:
                    if f.modification_time:
                        latest = max(latest, f.modification_time.timestamp())
            return latest

        return max(workflows, key=get_latest_activity)

    def _generate_sqlite_workflow_dashboard(self, workflow: Dict[str, Any]):
        """Generate dashboard layout for a SQLite workflow (main + sub-agents).

        Args:
            workflow: Workflow dict from SQLiteProcessor.get_most_recent_workflow()

        Returns:
            Rich layout for the dashboard
        """
        # Get all files from all sessions in the workflow
        all_files = []
        for session in workflow["all_sessions"]:
            all_files.extend(session.files)

        # Get the most recent file across all sessions
        recent_file = None
        if all_files:
            recent_file = max(
                all_files,
                key=lambda f: (
                    f.time_data.created if f.time_data and f.time_data.created else 0
                ),
            )

        # Calculate output rate across entire workflow
        output_rate = self._calculate_sqlite_workflow_output_rate(workflow)

        # Get model pricing for quota and context window
        quota = None
        context_window = 200000  # Default

        if recent_file and recent_file.model_id in self.pricing_data:
            model_pricing = self.pricing_data[recent_file.model_id]
            quota = model_pricing.session_quota
            context_window = model_pricing.context_window

        # Create a workflow wrapper for the dashboard UI
        workflow_wrapper = WorkflowWrapper(workflow, self.pricing_data)

        # Use the existing dashboard UI
        # Note: WorkflowWrapper mimics SessionWorkflow interface for dashboard compatibility
        from typing import Any, cast

        return self.dashboard_ui.create_dashboard_layout(
            session=workflow["main_session"],
            recent_file=recent_file,
            pricing_data=self.pricing_data,
            burn_rate=output_rate,
            quota=quota,
            context_window=context_window,
            workflow=cast(Any, workflow_wrapper),
        )

    def _calculate_sqlite_workflow_output_rate(self, workflow: Dict[str, Any]) -> float:
        """Calculate output token rate across SQLite workflow.

        Args:
            workflow: Workflow containing all sessions

        Returns:
            Output tokens per second over the last 5 minutes
        """
        # Get all files from all sessions
        all_files = []
        for session in workflow["all_sessions"]:
            all_files.extend(session.files)

        if not all_files:
            return 0.0

        # Calculate the cutoff time (5 minutes ago)
        cutoff_time = datetime.now() - timedelta(minutes=5)

        # Filter interactions from the last 5 minutes
        recent_interactions = []
        for f in all_files:
            if f.time_data and f.time_data.created:
                file_time = datetime.fromtimestamp(f.time_data.created / 1000)
                if file_time >= cutoff_time:
                    recent_interactions.append(f)

        if not recent_interactions:
            return 0.0

        # Sum output tokens from recent interactions
        total_output_tokens = sum(f.tokens.output for f in recent_interactions)

        if total_output_tokens == 0:
            return 0.0

        # Sum active processing time (duration_ms) from recent interactions
        total_duration_ms = 0
        for f in recent_interactions:
            if f.time_data and f.time_data.duration_ms:
                total_duration_ms += f.time_data.duration_ms

        # Convert to seconds
        total_duration_seconds = total_duration_ms / 1000

        if total_duration_seconds > 0:
            return total_output_tokens / total_duration_seconds

        return 0.0

    def validate_monitoring_setup(
        self, base_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """Validate that monitoring can be set up properly.

        Args:
            base_path: Path to directory containing sessions (optional, for legacy mode)

        Returns:
            Validation results
        """
        issues = []
        warnings = []
        info = {}

        # First check for SQLite database (v1.2.0+)
        db_path = SQLiteProcessor.find_database_path()
        if db_path:
            stats = SQLiteProcessor.get_database_stats(db_path)
            if stats.get("exists"):
                info["sqlite"] = {
                    "available": True,
                    "path": str(db_path),
                    "sessions": stats.get("session_count", 0),
                    "sub_agents": stats.get("sub_agent_count", 0),
                }
            else:
                warnings.append("SQLite database found but cannot read stats")
        else:
            info["sqlite"] = {"available": False}

        # Check for file-based storage (legacy)
        base_path = base_path or (
            self.paths_config.messages_dir if self.paths_config else None
        )
        if base_path:
            base_path_obj = Path(base_path)
            if base_path_obj.exists() and base_path_obj.is_dir():
                session_dirs = FileProcessor.find_session_directories(base_path)
                if session_dirs:
                    info["files"] = {
                        "available": True,
                        "path": str(base_path),
                        "sessions": len(session_dirs),
                    }
                else:
                    info["files"] = {
                        "available": True,
                        "path": str(base_path),
                        "sessions": 0,
                    }
            else:
                info["files"] = {"available": False}
        else:
            info["files"] = {"available": False}

        # Check pricing data
        if not self.pricing_data:
            warnings.append("No pricing data available - costs will show as $0.00")

        # Determine if at least one source is available
        if not info["sqlite"]["available"] and not info["files"].get("available"):
            issues.append(
                "No session data source found. Expected SQLite database or file storage."
            )

        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "warnings": warnings,
            "info": info,
        }
