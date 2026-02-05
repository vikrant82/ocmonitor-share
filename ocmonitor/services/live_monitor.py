"""Live monitoring service for OpenCode Monitor."""

import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List
from rich.live import Live
from rich.console import Console

from ..models.session import SessionData, InteractionFile
from ..models.workflow import SessionWorkflow
from ..utils.file_utils import FileProcessor
from ..ui.dashboard import DashboardUI
from ..config import ModelPricing
from .session_grouper import SessionGrouper


class LiveMonitor:
    """Service for live monitoring of OpenCode sessions."""

    def __init__(self, pricing_data: Dict[str, ModelPricing], console: Optional[Console] = None):
        """Initialize live monitor.

        Args:
            pricing_data: Model pricing information
            console: Rich console for output
        """
        self.pricing_data = pricing_data
        self.console = console or Console()
        self.dashboard_ui = DashboardUI(console)
        self.session_grouper = SessionGrouper()

    def start_monitoring(self, base_path: str, refresh_interval: int = 5):
        """Start live monitoring of the most recent workflow (main session + sub-agents).

        Args:
            base_path: Path to directory containing sessions
            refresh_interval: Update interval in seconds
        """
        try:
            # Load recent sessions and group into workflows
            sessions = FileProcessor.load_all_sessions(base_path, limit=50)
            if not sessions:
                self.console.print(f"[red]No sessions found in {base_path}[/red]")
                return

            workflows = self.session_grouper.group_sessions(sessions)
            if not workflows:
                self.console.print(f"[red]No workflows found[/red]")
                return

            # Get the most recent workflow
            current_workflow = workflows[0]
            tracked_session_ids = set(s.session_id for s in current_workflow.all_sessions)

            self.console.print(f"[green]Starting live monitoring of workflow: {current_workflow.main_session.session_id}[/green]")
            if current_workflow.has_sub_agents:
                self.console.print(f"[cyan]Tracking {current_workflow.session_count} sessions (1 main + {current_workflow.sub_agent_count} sub-agents)[/cyan]")
            self.console.print(f"[cyan]Update interval: {refresh_interval} seconds[/cyan]")
            self.console.print("[dim]Press Ctrl+C to exit[/dim]\n")

            # Start live monitoring
            with Live(
                self._generate_workflow_dashboard(current_workflow),
                refresh_per_second=1/refresh_interval,
                console=self.console
            ) as live:
                while True:
                    # Reload all sessions and re-group
                    sessions = FileProcessor.load_all_sessions(base_path, limit=50)
                    workflows = self.session_grouper.group_sessions(sessions)

                    if workflows:
                        # Check if a new workflow started (different main session)
                        new_workflow = workflows[0]
                        if new_workflow.workflow_id != current_workflow.workflow_id:
                            # Check if the new main session is not a sub-agent of our current workflow
                            if new_workflow.main_session.session_id not in tracked_session_ids:
                                current_workflow = new_workflow
                                tracked_session_ids = set(s.session_id for s in current_workflow.all_sessions)
                                self.console.print(f"\n[yellow]New workflow detected: {current_workflow.main_session.session_id}[/yellow]")
                        else:
                            # Same workflow, update it
                            current_workflow = new_workflow
                            # Check for new sub-agents
                            new_ids = set(s.session_id for s in current_workflow.all_sessions)
                            new_subs = new_ids - tracked_session_ids
                            if new_subs:
                                for sub_id in new_subs:
                                    self.console.print(f"\n[cyan]New sub-agent detected: {sub_id}[/cyan]")
                                tracked_session_ids = new_ids

                    # Update dashboard
                    live.update(self._generate_workflow_dashboard(current_workflow))
                    time.sleep(refresh_interval)

        except KeyboardInterrupt:
            self.console.print("\n[yellow]Live monitoring stopped.[/yellow]")

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
            context_window=context_window
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
            workflow=workflow  # Pass workflow for additional display
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
            f for f in all_files
            if f.modification_time >= cutoff_time
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
            f for f in session.files
            if f.modification_time >= cutoff_time
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
            return {
                'status': 'no_sessions',
                'message': 'No sessions found'
            }

        recent_file = None
        if recent_session.files:
            recent_file = max(recent_session.files, key=lambda f: f.modification_time)

        # Calculate how long ago the last activity was
        last_activity = None
        if recent_file:
            last_activity = time.time() - recent_file.modification_time.timestamp()

        # Determine activity status
        activity_status = 'unknown'
        if last_activity is not None:
            if last_activity < 60:  # Less than 1 minute
                activity_status = 'active'
            elif last_activity < 300:  # Less than 5 minutes
                activity_status = 'recent'
            elif last_activity < 1800:  # Less than 30 minutes
                activity_status = 'idle'
            else:
                activity_status = 'inactive'

        return {
            'status': 'found',
            'session_id': recent_session.session_id,
            'interaction_count': recent_session.interaction_count,
            'total_tokens': recent_session.total_tokens.total,
            'total_cost': float(recent_session.calculate_total_cost(self.pricing_data)),
            'models_used': recent_session.models_used,
            'last_activity_seconds': last_activity,
            'activity_status': activity_status,
            'output_rate': self._calculate_output_rate(recent_session),
            'recent_file': {
                'name': recent_file.file_name,
                'model': recent_file.model_id,
                'tokens': recent_file.tokens.total
            } if recent_file else None
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
            'timestamp': time.time(),
            'session': {
                'id': recent_session.session_id,
                'interaction_count': recent_session.interaction_count,
                'total_tokens': recent_session.total_tokens.model_dump(),
                'total_cost': float(recent_session.calculate_total_cost(self.pricing_data)),
                'models_used': recent_session.models_used
            },
            'recent_interaction': {
                'file_name': recent_file.file_name,
                'model_id': recent_file.model_id,
                'tokens': recent_file.tokens.model_dump(),
                'cost': float(recent_file.calculate_cost(self.pricing_data)),
                'modification_time': recent_file.modification_time.isoformat()
            } if recent_file else None,
            'output_rate': self._calculate_output_rate(recent_session),
            'context_usage': self._calculate_context_usage(recent_file) if recent_file else None
        }

    def _calculate_context_usage(self, interaction_file: InteractionFile) -> Dict[str, Any]:
        """Calculate context window usage for an interaction.

        Args:
            interaction_file: Interaction file to analyze

        Returns:
            Context usage information
        """
        if interaction_file.model_id not in self.pricing_data:
            return {
                'context_size': 0,
                'context_window': 200000,
                'usage_percentage': 0.0
            }

        model_pricing = self.pricing_data[interaction_file.model_id]
        context_window = model_pricing.context_window

        # Context size = input + cache read + cache write
        context_size = (
            interaction_file.tokens.input +
            interaction_file.tokens.cache_read +
            interaction_file.tokens.cache_write
        )

        usage_percentage = (context_size / context_window) * 100 if context_window > 0 else 0

        return {
            'context_size': context_size,
            'context_window': context_window,
            'usage_percentage': min(100.0, usage_percentage)
        }

    def validate_monitoring_setup(self, base_path: str) -> Dict[str, Any]:
        """Validate that monitoring can be set up properly.

        Args:
            base_path: Path to directory containing sessions

        Returns:
            Validation results
        """
        issues = []
        warnings = []

        # Check if base path exists
        base_path_obj = Path(base_path)
        if not base_path_obj.exists():
            issues.append(f"Base path does not exist: {base_path}")
            return {
                'valid': False,
                'issues': issues,
                'warnings': warnings
            }

        if not base_path_obj.is_dir():
            issues.append(f"Base path is not a directory: {base_path}")
            return {
                'valid': False,
                'issues': issues,
                'warnings': warnings
            }

        # Check for session directories
        session_dirs = FileProcessor.find_session_directories(base_path)
        if not session_dirs:
            warnings.append("No session directories found")
        else:
            # Check most recent session
            recent_session = FileProcessor.load_session_data(session_dirs[0])
            if not recent_session:
                warnings.append("Most recent session directory contains no valid data")
            elif not recent_session.files:
                warnings.append("Most recent session has no interaction files")

        # Check pricing data
        if not self.pricing_data:
            warnings.append("No pricing data available - costs will show as $0.00")

        return {
            'valid': len(issues) == 0,
            'issues': issues,
            'warnings': warnings,
            'session_directories_found': len(session_dirs),
            'most_recent_session': session_dirs[0].name if session_dirs else None
        }