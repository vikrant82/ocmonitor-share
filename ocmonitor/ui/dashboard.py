"""Live dashboard UI components for OpenCode Monitor."""

import os
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Optional

from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ..models.session import SessionData
from ..models.workflow import SessionWorkflow
from ..utils.time_utils import TimeUtils
from ..utils.formatting import ColorFormatter


class DashboardUI:
    """UI components for the live dashboard."""

    def __init__(self, console: Optional[Console] = None):
        """Initialize dashboard UI.

        Args:
            console: Rich console instance. If None, creates a new one.
        """
        self.console = console or Console()

    def create_header(
        self, session: SessionData, workflow: Optional[SessionWorkflow] = None
    ) -> Panel:
        """Create header panel with session info."""
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if workflow and workflow.has_sub_agents:
            # Show workflow info with sub-agent count
            header_text = (
                f"[dashboard.header]OpenCode Live Dashboard[/dashboard.header]  "
                f"[metric.label]Project:[/metric.label] [dashboard.project]{workflow.project_name}[/dashboard.project]  "
                f"[metric.label]Session:[/metric.label] [dashboard.session]{workflow.display_title}[/dashboard.session]  "
                f"[metric.label]Updated:[/metric.label] [metric.value]{current_time}[/metric.value]  "
                f"[metric.label]Workflow:[/metric.label] [dashboard.info]{workflow.session_count} sessions[/dashboard.info] "
                f"[metric.label]([/metric.label][metric.value]1 main + {workflow.sub_agent_count} sub[/metric.value][metric.label])[/metric.label]"
            )
        else:
            header_text = (
                f"[dashboard.header]OpenCode Live Dashboard[/dashboard.header]  "
                f"[metric.label]Project:[/metric.label] [dashboard.project]{session.project_name}[/dashboard.project]  "
                f"[metric.label]Session:[/metric.label] [dashboard.session]{session.display_title}[/dashboard.session]  "
                f"[metric.label]Updated:[/metric.label] [metric.value]{current_time}[/metric.value]  "
                f"[metric.label]Interactions:[/metric.label] [metric.value]{session.interaction_count}[/metric.value]"
            )

        return Panel(
            header_text,
            title=Text("Dashboard", style="dashboard.title"),
            title_align="left",
            border_style="dashboard.border",
        )

    def create_token_panel(
        self, session: SessionData, recent_file: Optional[Any] = None
    ) -> Panel:
        """Create token consumption panel."""
        session_tokens = session.total_tokens

        # Create compact horizontal layout
        if recent_file:
            token_text = (
                f"[dashboard.header]Recent Interaction[/dashboard.header]\n"
                f"[metric.label]Input:[/metric.label] [metric.value]{recent_file.tokens.input:,}[/metric.value]    "
                f"[metric.label]Cache W:[/metric.label] [metric.value]{recent_file.tokens.cache_write:,}[/metric.value]\n"
                f"[metric.label]Output:[/metric.label] [metric.value]{recent_file.tokens.output:,}[/metric.value]   "
                f"[metric.label]Cache R:[/metric.label] [metric.value]{recent_file.tokens.cache_read:,}[/metric.value]\n\n"
                f"[dashboard.header]Session Totals[/dashboard.header]\n"
                f"[metric.label]Input:[/metric.label] [metric.value]{session_tokens.input:,}[/metric.value]    "
                f"[metric.label]Cache W:[/metric.label] [metric.value]{session_tokens.cache_write:,}[/metric.value]\n"
                f"[metric.label]Output:[/metric.label] [metric.value]{session_tokens.output:,}[/metric.value]   "
                f"[metric.label]Cache R:[/metric.label] [metric.value]{session_tokens.cache_read:,}[/metric.value]\n"
                f"[metric.label]Total:[/metric.label] [metric.tokens]{session_tokens.total:,}[/metric.tokens]"
            )
        else:
            token_text = (
                f"[dashboard.header]Session Totals[/dashboard.header]\n"
                f"[metric.label]Input:[/metric.label] [metric.value]{session_tokens.input:,}[/metric.value]    "
                f"[metric.label]Cache W:[/metric.label] [metric.value]{session_tokens.cache_write:,}[/metric.value]\n"
                f"[metric.label]Output:[/metric.label] [metric.value]{session_tokens.output:,}[/metric.value]   "
                f"[metric.label]Cache R:[/metric.label] [metric.value]{session_tokens.cache_read:,}[/metric.value]\n"
                f"[metric.label]Total:[/metric.label] [metric.tokens]{session_tokens.total:,}[/metric.tokens]"
            )

        return Panel(
            token_text,
            title=Text("Tokens", style="dashboard.title"),
            title_align="left",
            border_style="dashboard.border",
        )

    def create_cost_panel(
        self,
        session: SessionData,
        pricing_data: Dict[str, Any],
        quota: Optional[Decimal] = None,
    ) -> Panel:
        """Create cost tracking panel."""
        total_cost = session.calculate_total_cost(pricing_data)

        if quota:
            percentage = min(100, float(total_cost / quota) * 100)
            progress_bar = self.create_compact_progress_bar(percentage)
            cost_color = self.get_cost_color(percentage)

            cost_text = (
                f"[dashboard.header]Cost Tracking[/dashboard.header]\n"
                f"[metric.label]Session:[/metric.label] [metric.cost]${total_cost:.2f}[/metric.cost]\n"
                f"[metric.label]Quota:[/metric.label] [metric.cost]${quota:.2f}[/metric.cost]\n"
                f"[{cost_color}]{progress_bar}[/{cost_color}]"
            )
        else:
            cost_text = (
                f"[dashboard.header]Cost Tracking[/dashboard.header]\n"
                f"[metric.label]Session:[/metric.label] [metric.cost]${total_cost:.2f}[/metric.cost]\n"
                f"[metric.label]No quota configured[/metric.label]"
            )

        return Panel(
            cost_text,
            title=Text("Cost", style="dashboard.title"),
            title_align="left",
            border_style="dashboard.border",
        )

    def create_model_panel(
        self, session: SessionData, pricing_data: Dict[str, Any]
    ) -> Panel:
        """Create model usage panel."""
        model_breakdown = session.get_model_breakdown(pricing_data)

        if not model_breakdown:
            return Panel(
                "[metric.label]No model data available[/metric.label]",
                title=Text("Models", style="dashboard.title"),
                border_style="dashboard.border",
            )

        model_lines = []
        for model, stats in model_breakdown.items():
            model_name = model[:25] + "..." if len(model) > 28 else model
            model_lines.append(
                f"[metric.label]{model_name}[/metric.label]  "
                f"[metric.value]{stats['tokens'].total:,}[/metric.value] [metric.tokens]tokens[/metric.tokens]  "
                f"[metric.cost]${stats['cost']:.2f}[/metric.cost]"
            )

        model_text = "\n".join(model_lines)

        return Panel(
            model_text,
            title=Text("Models", style="dashboard.title"),
            title_align="left",
            border_style="dashboard.border",
        )

    def create_context_panel(
        self, recent_file: Optional[Any], context_window: int = 200000
    ) -> Panel:
        """Create context window status panel."""
        if not recent_file:
            return Panel(
                "[metric.label]No recent interaction[/metric.label]",
                title=Text("Context", style="dashboard.title"),
                border_style="dashboard.border",
            )

        # Calculate context size (input + cache read + cache write from most recent)
        context_size = (
            recent_file.tokens.input
            + recent_file.tokens.cache_read
            + recent_file.tokens.cache_write
        )

        percentage = min(100, (context_size / context_window) * 100)
        progress_bar = self.create_compact_progress_bar(percentage, 12)
        context_color = self.get_context_color(percentage)

        context_text = (
            f"[metric.label]Size:[/metric.label] [metric.value]{context_size:,}[/metric.value]\n"
            f"[metric.label]Window:[/metric.label] [metric.value]{context_window:,}[/metric.value]\n"
            f"[{context_color}]{progress_bar}[/{context_color}]"
        )

        return Panel(
            context_text,
            title=Text("Context", style="dashboard.title"),
            title_align="left",
            border_style="dashboard.border",
        )

    def create_burn_rate_panel(self, burn_rate: float) -> Panel:
        """Create output token rate panel (tokens per second)."""
        if burn_rate == 0:
            burn_text = "[metric.label]No recent activity[/metric.label]"
        else:
            # Add level indicator
            if burn_rate > 90:
                level = "[status.error]VERY FAST[/status.error]"
            elif burn_rate > 60:
                level = "[status.info]FAST[/status.info]"
            elif burn_rate >= 25:
                level = "[status.warning]MEDIUM[/status.warning]"
            else:
                level = "[status.success]SLOW[/status.success]"

            burn_text = (
                f"[metric.value]{burn_rate:,.1f}[/metric.value] [metric.tokens]tok/sec[/metric.tokens]\n"
                f"{level}"
            )

        return Panel(
            burn_text,
            title=Text("Output Rate", style="dashboard.title"),
            title_align="left",
            border_style="dashboard.border",
        )

    def create_session_time_panel(self, session: SessionData) -> Panel:
        """Create session time progress panel with 5-hour maximum."""
        if not session.start_time:
            return Panel(
                "[metric.label]No session timing data[/metric.label]",
                title=Text("Session Time", style="dashboard.title"),
                border_style="dashboard.border",
            )

        # Calculate duration from start_time to now (updates continuously even when idle)
        current_time = datetime.now()
        session_duration = current_time - session.start_time
        duration_ms = int(session_duration.total_seconds() * 1000)

        # Calculate percentage based on 5-hour maximum
        max_hours = 5.0
        duration_hours = session_duration.total_seconds() / 3600
        percentage = min(100.0, (duration_hours / max_hours) * 100.0)

        # Format duration display using hours and minutes format
        duration_display = TimeUtils.format_duration_hm(duration_ms)

        # Create progress bar with time-based colors
        progress_bar = self.create_compact_progress_bar(percentage, 12)
        time_color = self.get_time_color(percentage)

        time_text = (
            f"[metric.label]Duration:[/metric.label] [metric.value]{duration_display}[/metric.value]\n"
            f"[metric.label]Max:[/metric.label] [metric.value]{max_hours:.0f}h[/metric.value]\n"
            f"[{time_color}]{progress_bar}[/{time_color}]"
        )

        return Panel(
            time_text,
            title=Text("Session Time", style="dashboard.title"),
            title_align="left",
            border_style="dashboard.border",
        )

    def create_recent_file_panel(self, recent_file: Optional[Any]) -> Panel:
        """Create recent file info panel."""
        if not recent_file:
            return Panel(
                "[metric.label]No recent files[/metric.label]",
                title=Text("Recent", style="dashboard.title"),
                border_style="dashboard.border",
            )

        # Truncate file name if too long
        file_name = recent_file.file_name
        if len(file_name) > 20:
            file_name = "..." + file_name[-17:]

        file_text = (
            f"[metric.label]File:[/metric.label] [metric.value]{file_name}[/metric.value]\n"
            f"[metric.label]Model:[/metric.label] [metric.value]{recent_file.model_id[:15]}[/metric.value]"
        )

        if recent_file.time_data and recent_file.time_data.duration_ms:
            duration = self.format_duration(recent_file.time_data.duration_ms)
            file_text += f"\n[metric.label]Duration:[/metric.label] [metric.value]{duration}[/metric.value]"

        return Panel(
            file_text,
            title=Text("Recent", style="dashboard.title"),
            title_align="left",
            border_style="dashboard.border",
        )

    def create_dashboard_layout(
        self,
        session: SessionData,
        recent_file: Optional[Any],
        pricing_data: Dict[str, Any],
        burn_rate: float,
        quota: Optional[Decimal] = None,
        context_window: int = 200000,
        workflow: Optional[SessionWorkflow] = None,
    ) -> Layout:
        """Create the complete dashboard layout."""
        layout = Layout()

        # Use workflow data if available, otherwise use session data
        if workflow and workflow.has_sub_agents:
            # Create panels using workflow totals
            header = self.create_header(session, workflow)
            token_panel = self.create_workflow_token_panel(workflow, recent_file)
            cost_panel = self.create_workflow_cost_panel(workflow, pricing_data, quota)
            model_panel = self.create_workflow_model_panel(workflow, pricing_data)
            session_time_panel = self.create_workflow_time_panel(workflow)
        else:
            # Create panels using single session data
            header = self.create_header(session)
            token_panel = self.create_token_panel(session, recent_file)
            cost_panel = self.create_cost_panel(session, pricing_data, quota)
            model_panel = self.create_model_panel(session, pricing_data)
            session_time_panel = self.create_session_time_panel(session)

        context_panel = self.create_context_panel(recent_file, context_window)
        burn_rate_panel = self.create_burn_rate_panel(burn_rate)
        recent_file_panel = self.create_recent_file_panel(recent_file)

        # Setup new 4-section layout structure
        layout.split_column(
            Layout(header, size=3),  # Compact header
            Layout(name="primary", minimum_size=8),  # Main metrics
            Layout(name="secondary", size=6),  # Compact metrics
            Layout(name="models", minimum_size=4),  # Model breakdown
        )

        # Primary section: Token usage (60%) and Cost tracking (40%)
        layout["primary"].split_row(
            Layout(token_panel, ratio=3),  # 60% for token data
            Layout(cost_panel, ratio=2),  # 40% for cost data
        )

        # Secondary section: Four compact panels
        layout["secondary"].split_row(
            Layout(context_panel, ratio=1),
            Layout(burn_rate_panel, ratio=1),
            Layout(session_time_panel, ratio=1),
            Layout(recent_file_panel, ratio=1),
        )

        # Models section: Full width for model breakdown
        layout["models"].update(model_panel)

        return layout

    def create_progress_bar(self, percentage: float, width: int = 30) -> str:
        """Create a text-based progress bar."""
        filled = int(width * percentage / 100)
        bar = "█" * filled + "░" * (width - filled)
        return f"[{bar}] {percentage:.1f}%"

    def create_compact_progress_bar(self, percentage: float, width: int = 20) -> str:
        """Create a compact progress bar for space-efficient display."""
        filled = int(width * percentage / 100)
        bar = "▌" * filled + "░" * (width - filled)
        return f"{bar} {percentage:.0f}%"

    def get_cost_color(self, percentage: float) -> str:
        """Get color for cost based on percentage."""
        return ColorFormatter.get_color_by_percentage(percentage)

    def get_context_color(self, percentage: float) -> str:
        """Get color for context window based on percentage."""
        return ColorFormatter.get_color_by_percentage(percentage)

    def get_time_color(self, percentage: float) -> str:
        """Get color for session time based on percentage of 5-hour max."""
        return ColorFormatter.get_color_by_percentage(percentage)

    def format_duration(self, milliseconds: int) -> str:
        """Format duration in milliseconds to hours and minutes format."""
        return TimeUtils.format_duration_hm(milliseconds)

    def clear_screen(self):
        """Clear the terminal screen."""
        os.system("cls" if os.name == "nt" else "clear")

    def create_simple_table(self, data: Dict[str, Any]) -> Table:
        """Create a simple data table for fallback rendering."""
        table = Table(show_header=False, box=None)
        table.add_column("Key", style="metric.important")
        table.add_column("Value", style="metric.value")

        for key, value in data.items():
            table.add_row(key, str(value))

        return table

    def create_workflow_token_panel(
        self, workflow: SessionWorkflow, recent_file: Optional[Any] = None
    ) -> Panel:
        """Create token consumption panel for workflow."""
        workflow_tokens = workflow.total_tokens

        # Create compact horizontal layout showing workflow totals
        if recent_file:
            token_text = (
                f"[dashboard.header]Recent Interaction[/dashboard.header]\n"
                f"[metric.label]Input:[/metric.label] [metric.value]{recent_file.tokens.input:,}[/metric.value]    "
                f"[metric.label]Cache W:[/metric.label] [metric.value]{recent_file.tokens.cache_write:,}[/metric.value]\n"
                f"[metric.label]Output:[/metric.label] [metric.value]{recent_file.tokens.output:,}[/metric.value]   "
                f"[metric.label]Cache R:[/metric.label] [metric.value]{recent_file.tokens.cache_read:,}[/metric.value]\n\n"
                f"[dashboard.header]Workflow Totals[/dashboard.header] [metric.label]({workflow.session_count} sessions)[/metric.label]\n"
                f"[metric.label]Input:[/metric.label] [metric.value]{workflow_tokens.input:,}[/metric.value]    "
                f"[metric.label]Cache W:[/metric.label] [metric.value]{workflow_tokens.cache_write:,}[/metric.value]\n"
                f"[metric.label]Output:[/metric.label] [metric.value]{workflow_tokens.output:,}[/metric.value]   "
                f"[metric.label]Cache R:[/metric.label] [metric.value]{workflow_tokens.cache_read:,}[/metric.value]\n"
                f"[metric.label]Total:[/metric.label] [metric.tokens]{workflow_tokens.total:,}[/metric.tokens]"
            )
        else:
            token_text = (
                f"[dashboard.header]Workflow Totals[/dashboard.header] [metric.label]({workflow.session_count} sessions)[/metric.label]\n"
                f"[metric.label]Input:[/metric.label] [metric.value]{workflow_tokens.input:,}[/metric.value]    "
                f"[metric.label]Cache W:[/metric.label] [metric.value]{workflow_tokens.cache_write:,}[/metric.value]\n"
                f"[metric.label]Output:[/metric.label] [metric.value]{workflow_tokens.output:,}[/metric.value]   "
                f"[metric.label]Cache R:[/metric.label] [metric.value]{workflow_tokens.cache_read:,}[/metric.value]\n"
                f"[metric.label]Total:[/metric.label] [metric.tokens]{workflow_tokens.total:,}[/metric.tokens]"
            )

        return Panel(
            token_text,
            title=Text("Tokens", style="dashboard.title"),
            title_align="left",
            border_style="dashboard.border",
        )

    def create_workflow_cost_panel(
        self,
        workflow: SessionWorkflow,
        pricing_data: Dict[str, Any],
        quota: Optional[Decimal] = None,
    ) -> Panel:
        """Create cost tracking panel for workflow."""
        total_cost = workflow.calculate_total_cost(pricing_data)

        if quota:
            percentage = min(100, float(total_cost / quota) * 100)
            progress_bar = self.create_compact_progress_bar(percentage)
            cost_color = self.get_cost_color(percentage)

            cost_text = (
                f"[dashboard.header]Workflow Cost[/dashboard.header]\n"
                f"[metric.label]Total:[/metric.label] [metric.cost]${total_cost:.2f}[/metric.cost]\n"
                f"[metric.label]Quota:[/metric.label] [metric.cost]${quota:.2f}[/metric.cost]\n"
                f"[{cost_color}]{progress_bar}[/{cost_color}]"
            )
        else:
            cost_text = (
                f"[dashboard.header]Workflow Cost[/dashboard.header]\n"
                f"[metric.label]Total:[/metric.label] [metric.cost]${total_cost:.2f}[/metric.cost]\n"
                f"[metric.label]No quota configured[/metric.label]"
            )

        return Panel(
            cost_text,
            title=Text("Cost", style="dashboard.title"),
            title_align="left",
            border_style="dashboard.border",
        )

    def create_workflow_model_panel(
        self, workflow: SessionWorkflow, pricing_data: Dict[str, Any]
    ) -> Panel:
        """Create model usage panel for workflow."""
        from collections import defaultdict

        # Aggregate model stats across all sessions
        model_data: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {"tokens": 0, "cost": Decimal("0.0")}
        )

        for session in workflow.all_sessions:
            model_breakdown = session.get_model_breakdown(pricing_data)
            for model, stats in model_breakdown.items():
                model_data[model]["tokens"] += stats["tokens"].total
                model_data[model]["cost"] += stats["cost"]

        if not model_data:
            return Panel(
                "[metric.label]No model data available[/metric.label]",
                title=Text("Models", style="dashboard.title"),
                border_style="dashboard.border",
            )

        model_lines = []
        for model, stats in sorted(
            model_data.items(), key=lambda x: x[1]["cost"], reverse=True
        ):
            model_name = model[:25] + "..." if len(model) > 28 else model
            model_lines.append(
                f"[metric.label]{model_name}[/metric.label]  "
                f"[metric.value]{stats['tokens']:,}[/metric.value] [metric.tokens]tokens[/metric.tokens]  "
                f"[metric.cost]${stats['cost']:.2f}[/metric.cost]"
            )

        model_text = "\n".join(model_lines)

        return Panel(
            model_text,
            title=Text("Models", style="dashboard.title"),
            title_align="left",
            border_style="dashboard.border",
        )

    def create_workflow_time_panel(self, workflow: SessionWorkflow) -> Panel:
        """Create session time progress panel for workflow."""
        if not workflow.start_time:
            return Panel(
                "[metric.label]No workflow timing data[/metric.label]",
                title=Text("Workflow Time", style="dashboard.title"),
                border_style="dashboard.border",
            )

        # Calculate duration from workflow start_time to now
        current_time = datetime.now()
        workflow_duration = current_time - workflow.start_time
        duration_ms = int(workflow_duration.total_seconds() * 1000)

        # Calculate percentage based on 5-hour maximum
        max_hours = 5.0
        duration_hours = workflow_duration.total_seconds() / 3600
        percentage = min(100.0, (duration_hours / max_hours) * 100.0)

        # Format duration display
        duration_display = TimeUtils.format_duration_hm(duration_ms)

        # Create progress bar with time-based colors
        progress_bar = self.create_compact_progress_bar(percentage, 12)
        time_color = self.get_time_color(percentage)

        time_text = (
            f"[metric.label]Duration:[/metric.label] [metric.value]{duration_display}[/metric.value]\n"
            f"[metric.label]Max:[/metric.label] [metric.value]{max_hours:.0f}h[/metric.value]\n"
            f"[{time_color}]{progress_bar}[/{time_color}]"
        )

        return Panel(
            time_text,
            title=Text("Workflow Time", style="dashboard.title"),
            title_align="left",
            border_style="dashboard.border",
        )

