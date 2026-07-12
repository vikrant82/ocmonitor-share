"""Live dashboard UI components for OpenCode Monitor."""

import os
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ..models.session import SessionData, TokenUsage
from ..models.tool_usage import ToolUsageStats, ModelToolUsage
from ..models.workflow import SessionWorkflow
from ..utils.formatting import ColorFormatter
from ..utils.time_utils import TimeUtils


class DashboardUI:
    """UI components for the live dashboard."""

    def __init__(self, console: Optional[Console] = None, currency_converter=None):
        """Initialize dashboard UI.

        Args:
            console: Rich console instance. If None, creates a new one.
            currency_converter: Optional CurrencyConverter for currency formatting.
        """
        self.console = console or Console()
        self.currency_converter = currency_converter

    def _fmt_cost(self, amount: Decimal) -> str:
        """Format cost amount using currency converter."""
        if self.currency_converter:
            return self.currency_converter.format(amount)
        return f"${amount:.2f}"

    def _fmt_compact_count(self, value: float) -> str:
        """Format a count compactly for dense dashboard rows."""
        abs_value = abs(value)
        if abs_value >= 1_000_000:
            formatted = f"{value / 1_000_000:.1f}M"
        elif abs_value >= 1_000:
            formatted = f"{value / 1_000:.1f}k"
        else:
            formatted = f"{value:.0f}"
        return formatted.replace(".0M", "M").replace(".0k", "k")

    def _format_tool_token_suffix(self, stat: ToolUsageStats) -> str:
        """Format compact attributed per-tool token details for a tool row."""
        if stat.total_tokens <= 0:
            return ""

        avg_tokens = stat.total_tokens / stat.total_calls if stat.total_calls else 0.0

        return (
            f"  [metric.tokens]{self._fmt_compact_count(stat.total_tokens)}[/metric.tokens] tok"
            f" avg [metric.value]{self._fmt_compact_count(avg_tokens)}[/metric.value]/call"
            f" · I [metric.value]{self._fmt_compact_count(stat.input_tokens)}[/metric.value]"
            f" O [metric.value]{self._fmt_compact_count(stat.output_tokens)}[/metric.value]"
            f" CR [metric.value]{self._fmt_compact_count(stat.cache_read_tokens)}[/metric.value]"
            f" CW [metric.value]{self._fmt_compact_count(stat.cache_write_tokens)}[/metric.value]"
        )

    def _split_agent_model_key(self, key: str) -> Tuple[Optional[str], str]:
        """Split an optional agent/model grouping key into display parts."""
        if "::" in key:
            agent, model = key.split("::", 1)
            return agent or None, model
        return None, key

    def _agent_model_lookup_key(
        self, agent_name: Optional[str], model_name: str
    ) -> str:
        """Build the canonical dashboard lookup key for an agent/model pair."""
        return SessionData.agent_model_key(agent_name or "main", model_name)

    def _bare_lookup_key(self, key: str) -> str:
        """Return a provider-stripped lookup key while preserving agent scope."""
        agent, model = self._split_agent_model_key(key)
        bare_model = model.split("/", 1)[-1]
        return self._agent_model_lookup_key(agent, bare_model)

    def _format_agent_model_title(
        self,
        agent_name: Optional[str],
        model_name: str,
        include_agent: bool = True,
        max_length: int = 60,
    ) -> str:
        """Format a compact title for an agent/model dashboard pane."""
        title = (
            f"{agent_name or 'main'} / {model_name}" if include_agent else model_name
        )
        if len(title) > max_length:
            return title[: max_length - 3] + "..."
        return title

    def _describe_activity(
        self, last_activity_seconds: Optional[float]
    ) -> Tuple[str, str]:
        """Map seconds-since-last-activity to a (status_label, style) pair.

        Mirrors the thresholds used by LiveMonitor.get_session_status so the
        live header and the status API agree on what "active/idle" means.
        """
        if last_activity_seconds is None:
            return "unknown", "dim"
        if last_activity_seconds < 60:
            return "active", "status.success"
        if last_activity_seconds < 300:
            return "recent", "status.info"
        if last_activity_seconds < 1800:
            return "idle", "status.warning"
        return "inactive", "status.error"

    def _format_activity_indicator(
        self, last_activity_seconds: Optional[float]
    ) -> str:
        """Build a compact colored '● STATUS (Xs ago)' indicator for the header."""
        label, style = self._describe_activity(last_activity_seconds)
        if last_activity_seconds is None:
            ago = "no activity yet"
        else:
            secs = int(last_activity_seconds)
            if secs < 60:
                ago = f"{secs}s ago"
            elif secs < 3600:
                ago = f"{secs // 60}m ago"
            elif secs < 86400:
                ago = f"{secs // 3600}h ago"
            else:
                ago = f"{secs // 86400}d ago"
        return f"[{style}]● {label.upper()}[/{style}] [dim]({ago})[/dim]"

    def _recent_activity_seconds(
        self, recent_file: Optional[Any]
    ) -> Optional[float]:
        """Seconds since the most recent interaction, robust to placeholder paths.

        Prefers embedded time_data (which is present for SQLite-sourced
        interactions whose file_path is a non-existent placeholder) and only
        falls back to the filesystem mtime for file-based interactions. A raw
        modification_time read would raise FileNotFoundError in SQLite mode.
        """
        if recent_file is None:
            return None

        activity_ts: Optional[float] = None
        time_data = getattr(recent_file, "time_data", None)
        if time_data is not None:
            if getattr(time_data, "completed", None) is not None:
                activity_ts = time_data.completed / 1000
            elif getattr(time_data, "created", None) is not None:
                activity_ts = time_data.created / 1000

        if activity_ts is None:
            try:
                activity_ts = recent_file.modification_time.timestamp()
            except (FileNotFoundError, OSError, ValueError, AttributeError, TypeError):
                return None

        return max(0.0, datetime.now().timestamp() - activity_ts)

    def create_header(
        self,
        session: SessionData,
        workflow: Optional[SessionWorkflow] = None,
        controls_hint: Optional[str] = None,
        activity_indicator: Optional[str] = None,
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

        if activity_indicator:
            header_text += (
                f"  [metric.label]Activity:[/metric.label] {activity_indicator}"
            )

        return Panel(
            header_text,
            title=Text("Dashboard", style="dashboard.title"),
            title_align="left",
            border_style="dashboard.border",
        )

    def create_controls_panel(self, controls_hint: str) -> Panel:
        """Create dedicated controls panel for live keybind hints."""
        controls_text = f"[dim]{controls_hint}[/dim]"
        return Panel(
            controls_text,
            title=Text("Controls", style="dashboard.title"),
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
                f"[metric.label]Session:[/metric.label] [metric.cost]{self._fmt_cost(total_cost)}[/metric.cost]\n"
                f"[metric.label]Quota:[/metric.label] [metric.cost]{self._fmt_cost(quota)}[/metric.cost]\n"
                f"[{cost_color}]{progress_bar}[/{cost_color}]"
            )
        else:
            cost_text = (
                f"[dashboard.header]Cost Tracking[/dashboard.header]\n"
                f"[metric.label]Session:[/metric.label] [metric.cost]{self._fmt_cost(total_cost)}[/metric.cost]\n"
                f"[metric.label]No quota configured[/metric.label]"
            )

        return Panel(
            cost_text,
            title=Text("Cost", style="dashboard.title"),
            title_align="left",
            border_style="dashboard.border",
        )

    def create_model_panel(
        self,
        session: SessionData,
        pricing_data: Dict[str, Any],
        per_model_output_rates: Optional[Dict[str, float]] = None,
        per_model_context: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Panel:
        """Create model usage panel."""
        model_breakdown = session.get_model_breakdown(pricing_data)
        per_model_output_rates = per_model_output_rates or {}
        per_model_context = per_model_context or {}

        if not model_breakdown:
            return Panel(
                "[metric.label]No model data available[/metric.label]",
                title=Text("Models", style="dashboard.title"),
                border_style="dashboard.border",
            )

        model_lines = []
        for model, stats in model_breakdown.items():
            model_name = model[:35] + "..." if len(model) > 38 else model

            # Get context usage for this model
            context_info = per_model_context.get(model, {})
            context_pct = context_info.get("usage_percentage", 0.0)
            context_bar = self.create_compact_progress_bar(context_pct, 8)

            # Get output rate for this model
            output_rate = per_model_output_rates.get(model, 0.0)
            rate_str = f" - {output_rate:.1f} tok/s" if output_rate > 0 else ""

            model_lines.append(
                f"[metric.label]{model_name}[/metric.label]\n"
                f"  └─ Tokens: [metric.value]{stats['tokens'].total:,}[/metric.value] tok "
                f"(In: [metric.value]{stats['tokens'].input:,}[/metric.value] | "
                f"Out: [metric.value]{stats['tokens'].output:,}[/metric.value] | "
                f"CW: [metric.value]{stats['tokens'].cache_write:,}[/metric.value] | "
                f"CR: [metric.value]{stats['tokens'].cache_read:,}[/metric.value])\n"
                f"  └─ Cost: [metric.cost]{self._fmt_cost(stats['cost'])}[/metric.cost]  -  "
                f"context {context_bar}{rate_str}"
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

    def create_burn_rate_panel(
        self,
        burn_rate: float,
        per_model_rates: Optional[Dict[str, float]] = None,
    ) -> Panel:
        """Create output token rate panel (tokens per second).

        Shows the aggregate 5-minute p50 rate with a speed band, and — when
        per-agent/model rates are supplied — a compact per-model breakdown so
        the panel fills its column with useful signal instead of whitespace.
        """
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

            lines = [
                f"[metric.value]{burn_rate:,.1f}[/metric.value] "
                f"[metric.tokens]tok/sec[/metric.tokens]  {level}",
                "[dim]5-min p50 · workflow[/dim]",
            ]

            # Compact per-agent/model breakdown, highest rate first. These are
            # each model's p50 (matching the Tools panel "Rate"), so the panel
            # earns its column instead of trailing off into empty space.
            ranked = sorted(
                (
                    (key, rate)
                    for key, rate in (per_model_rates or {}).items()
                    if rate and rate > 0
                ),
                key=lambda item: item[1],
                reverse=True,
            )
            if ranked:
                lines.append(
                    "[dashboard.border]" + "─" * 24 + "[/dashboard.border]"
                )
                lines.append("[dim]by model[/dim]")
                for key, rate in ranked[:4]:
                    agent, model = self._split_agent_model_key(key)
                    bare_model = model.split("/", 1)[-1]
                    label = f"{agent}/{bare_model}" if agent else bare_model
                    if len(label) > 22:
                        label = label[:19] + "..."
                    lines.append(
                        f"[metric.label]{label}[/metric.label] "
                        f"[metric.value]{rate:.1f}[/metric.value] [dim]tok/s[/dim]"
                    )

            burn_text = "\n".join(lines)

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

    def create_status_panel(
        self,
        session: SessionData,
        pricing_data: Dict[str, Any],
        quota: Optional[Decimal] = None,
    ) -> Panel:
        """Create combined status panel with Cost + Session Time."""
        # --- Cost section ---
        total_cost = session.calculate_total_cost(pricing_data)

        if quota:
            percentage = min(100, float(total_cost / quota) * 100)
            progress_bar = self.create_compact_progress_bar(percentage, 10)
            cost_color = self.get_cost_color(percentage)
            cost_section = (
                f"[dashboard.header]Cost[/dashboard.header]\n"
                f"[metric.label]Session:[/metric.label] [metric.cost]{self._fmt_cost(total_cost)}[/metric.cost]  "
                f"[metric.label]Quota:[/metric.label] [metric.cost]{self._fmt_cost(quota)}[/metric.cost]\n"
                f"[{cost_color}]{progress_bar}[/{cost_color}]"
            )
        else:
            cost_section = (
                f"[dashboard.header]Cost[/dashboard.header]\n"
                f"[metric.label]Session:[/metric.label] [metric.cost]{self._fmt_cost(total_cost)}[/metric.cost]  "
                f"[dim]No quota[/dim]"
            )

        # --- Time section ---
        if session.start_time:
            current_time = datetime.now()
            session_duration = current_time - session.start_time
            duration_ms = int(session_duration.total_seconds() * 1000)
            max_hours = 5.0
            duration_hours = session_duration.total_seconds() / 3600
            percentage = min(100.0, (duration_hours / max_hours) * 100.0)
            duration_display = TimeUtils.format_duration_hm(duration_ms)
            progress_bar = self.create_compact_progress_bar(percentage, 10)
            time_color = self.get_time_color(percentage)
            time_section = (
                f"[dashboard.header]Time[/dashboard.header]\n"
                f"[metric.label]Duration:[/metric.label] [metric.value]{duration_display}[/metric.value]  "
                f"[metric.label]Max:[/metric.label] [metric.value]{max_hours:.0f}h[/metric.value]\n"
                f"[{time_color}]{progress_bar}[/{time_color}]"
            )
        else:
            time_section = (
                f"[dashboard.header]Time[/dashboard.header]\n[dim]No timing data[/dim]"
            )

        status_text = (
            f"{cost_section}\n"
            f"[dashboard.border]{'─' * 24}[/dashboard.border]\n"
            f"{time_section}"
        )

        return Panel(
            status_text,
            title=Text("Status", style="dashboard.title"),
            title_align="left",
            border_style="dashboard.border",
        )

    def create_workflow_status_panel(
        self,
        workflow: SessionWorkflow,
        pricing_data: Dict[str, Any],
        quota: Optional[Decimal] = None,
    ) -> Panel:
        """Create combined status panel with Workflow Cost + Workflow Time."""
        # --- Cost section ---
        total_cost = workflow.calculate_total_cost(pricing_data)

        if quota:
            percentage = min(100, float(total_cost / quota) * 100)
            progress_bar = self.create_compact_progress_bar(percentage, 10)
            cost_color = self.get_cost_color(percentage)
            cost_section = (
                f"[dashboard.header]Cost[/dashboard.header]\n"
                f"[metric.label]Total:[/metric.label] [metric.cost]{self._fmt_cost(total_cost)}[/metric.cost]  "
                f"[metric.label]Quota:[/metric.label] [metric.cost]{self._fmt_cost(quota)}[/metric.cost]\n"
                f"[{cost_color}]{progress_bar}[/{cost_color}]"
            )
        else:
            cost_section = (
                f"[dashboard.header]Cost[/dashboard.header]\n"
                f"[metric.label]Total:[/metric.label] [metric.cost]{self._fmt_cost(total_cost)}[/metric.cost]  "
                f"[dim]No quota[/dim]"
            )

        # --- Time section ---
        if workflow.start_time:
            current_time = datetime.now()
            workflow_duration = current_time - workflow.start_time
            duration_ms = int(workflow_duration.total_seconds() * 1000)
            max_hours = 5.0
            duration_hours = workflow_duration.total_seconds() / 3600
            percentage = min(100.0, (duration_hours / max_hours) * 100.0)
            duration_display = TimeUtils.format_duration_hm(duration_ms)
            progress_bar = self.create_compact_progress_bar(percentage, 10)
            time_color = self.get_time_color(percentage)
            time_section = (
                f"[dashboard.header]Time[/dashboard.header]\n"
                f"[metric.label]Duration:[/metric.label] [metric.value]{duration_display}[/metric.value]  "
                f"[metric.label]Max:[/metric.label] [metric.value]{max_hours:.0f}h[/metric.value]\n"
                f"[{time_color}]{progress_bar}[/{time_color}]"
            )
        else:
            time_section = (
                f"[dashboard.header]Time[/dashboard.header]\n[dim]No timing data[/dim]"
            )

        status_text = (
            f"{cost_section}\n"
            f"[dashboard.border]{'─' * 24}[/dashboard.border]\n"
            f"{time_section}"
        )

        return Panel(
            status_text,
            title=Text("Status", style="dashboard.title"),
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
            f"[metric.label]Model:[/metric.label] [metric.value]{recent_file.model_id[:35]}[/metric.value]"
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

    def create_tool_panel(
        self, tool_stats: List[ToolUsageStats], max_tools: int = 10
    ) -> Panel:
        """Create tool usage panel showing success/failure statistics.

        Args:
            tool_stats: List of tool usage statistics
            max_tools: Maximum number of tools to display

        Returns:
            Panel with tool usage information
        """
        if not tool_stats:
            return Panel(
                "[metric.label]No tool activity yet[/metric.label]",
                title=Text("Tools", style="dashboard.title"),
                title_align="left",
                border_style="dashboard.border",
            )

        lines = []
        for stat in tool_stats[:max_tools]:
            tool_name = stat.tool_name
            if len(tool_name) > 12:
                tool_name = tool_name[:9] + "..."

            success_rate = stat.success_rate
            bar = self.create_compact_progress_bar(success_rate, 10)
            color = self.get_tool_color(success_rate)

            lines.append(
                f"[metric.label]{tool_name:<12}[/metric.label] "
                f"[metric.value]{stat.total_calls:>4}[/metric.value] "
                f"[{color}]{bar}[/{color}]"
                f"{self._format_tool_token_suffix(stat)}"
            )

        tool_text = "\n".join(lines)

        return Panel(
            tool_text,
            title=Text("Tools", style="dashboard.title"),
            title_align="left",
            border_style="dashboard.border",
        )

    def get_tool_color(self, success_rate: float) -> str:
        """Get color for tool success rate.

        Args:
            success_rate: Success rate percentage

        Returns:
            Color string for styling
        """
        if success_rate >= 90:
            return "status.success"
        elif success_rate >= 70:
            return "status.warning"
        else:
            return "status.error"

    def create_model_tool_panel(
        self,
        model_tool_usage: ModelToolUsage,
        max_tools: int = 15,
        model_tokens: Optional[int] = None,
        model_token_details: Optional[Dict[str, int]] = None,
        model_interactions: Optional[int] = None,
        model_cost: Optional[Decimal] = None,
        context_pct: Optional[float] = None,
        context_size: Optional[int] = None,
        context_window: Optional[int] = None,
        output_rate: Optional[float] = None,
    ) -> Panel:
        """Create a panel showing tool usage for a single model.

        Args:
            model_tool_usage: ModelToolUsage containing model name and tool stats
            max_tools: Maximum number of tools to display
            model_tokens: Optional token count for this model to display in header
            model_token_details: Optional per-token-kind details for this model
            model_interactions: Optional interaction/message count for this model
            model_cost: Optional cost for this model to display in header
            context_pct: Optional context usage percentage for this model
            context_size: Optional recent context size for this model
            context_window: Optional context window for this model
            output_rate: Optional output rate (tok/sec) for this model

        Returns:
            Panel with tool usage information for this model
        """
        model_name = self._format_agent_model_title(
            model_tool_usage.agent_name,
            model_tool_usage.model_name,
            include_agent=model_tool_usage.agent_name is not None,
            max_length=35,
        )

        tool_stats = model_tool_usage.tool_stats[:max_tools]

        if not tool_stats:
            return Panel(
                "[metric.label]No tool activity[/metric.label]",
                title=Text(model_name, style="dashboard.title"),
                title_align="left",
                border_style="dashboard.border",
            )

        lines = []

        if model_tokens is not None:
            details = model_token_details or {"total": model_tokens}
            input_tokens = details.get("input", 0)
            output_tokens = details.get("output", 0)
            cache_read = details.get("cache_read", 0)
            cache_write = details.get("cache_write", 0)
            cache_total = cache_read + cache_write

            lines.append(
                f"[metric.label]Tokens:[/metric.label] "
                f"[metric.value]{model_tokens:,}[/metric.value] [metric.tokens]total[/metric.tokens]"
            )
            if model_interactions is not None:
                lines.append(
                    f"  Interactions [metric.value]{model_interactions:,}[/metric.value]"
                )
            lines.append(
                f"  Input [metric.value]{input_tokens:,}[/metric.value]  "
                f"Output [metric.value]{output_tokens:,}[/metric.value]"
            )
            lines.append(
                f"  Cache Read [metric.value]{cache_read:,}[/metric.value]  "
                f"Write [metric.value]{cache_write:,}[/metric.value]"
            )
            lines.append(f"  Cache Total [metric.value]{cache_total:,}[/metric.value]")

            if model_cost is not None or (output_rate is not None and output_rate > 0):
                perf_parts = []
                if model_cost is not None:
                    perf_parts.append(
                        f"Cost [metric.cost]{self._fmt_cost(model_cost)}[/metric.cost]"
                    )
                if output_rate is not None and output_rate > 0:
                    perf_parts.append(
                        f"Rate [metric.value]{output_rate:.1f}[/metric.value] tok/s"
                    )
                lines.append("  " + "  ".join(perf_parts))

            if context_pct is not None:
                context_bar = self.create_compact_progress_bar(context_pct, 8)
                if context_size is not None and context_window is not None:
                    lines.append(
                        f"  Ctx [metric.value]{context_size:,}[/metric.value]/"
                        f"[metric.value]{context_window:,}[/metric.value] {context_bar}"
                    )
                else:
                    lines.append(f"  Ctx {context_bar}")

            lines.append(
                "[dashboard.border]────────────────────────[/dashboard.border]"
            )

        for stat in tool_stats:
            tool_name = stat.tool_name
            if len(tool_name) > 12:
                tool_name = tool_name[:9] + "..."

            success_rate = stat.success_rate
            bar = self.create_compact_progress_bar(success_rate, 8)
            color = self.get_tool_color(success_rate)

            lines.append(
                f"[metric.label]{tool_name:<12}[/metric.label] "
                f"[metric.value]{stat.total_calls:>3}[/metric.value] "
                f"[{color}]{bar}[/{color}]"
                f"{self._format_tool_token_suffix(stat)}"
            )

        tool_text = "\n".join(lines)

        return Panel(
            tool_text,
            title=Text(model_name, style="dashboard.title"),
            title_align="left",
            border_style="dashboard.border",
        )

    def create_tool_grid_panel(
        self,
        tool_stats_by_model: List[ModelToolUsage],
        model_breakdown: Optional[Dict[str, Dict[str, Any]]] = None,
        per_model_output_rates: Optional[Dict[str, float]] = None,
        per_model_context: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Layout:
        """Create a 2-column grid layout for per-model tool panels.

        Args:
            tool_stats_by_model: List of ModelToolUsage (one per model)
            model_breakdown: Optional dict mapping model names to token/cost data
            per_model_output_rates: Optional dict mapping model to output rate
            per_model_context: Optional dict mapping model to context info

        Returns:
            Layout containing the grid of model tool panels
        """
        if not tool_stats_by_model:
            return Layout(
                Panel(
                    "[metric.label]No tool activity yet[/metric.label]",
                    title=Text("Tools", style="dashboard.title"),
                    title_align="left",
                    border_style="dashboard.border",
                )
            )

        if model_breakdown is None:
            model_breakdown = {}
        per_model_output_rates = per_model_output_rates or {}
        per_model_context = per_model_context or {}

        def _extract_token_details(tokens_value: Any) -> Dict[str, int]:
            """Extract token kind totals from TokenUsage-like, dict, or numeric values."""

            def _to_int(value: Any) -> int:
                try:
                    return int(value or 0)
                except (TypeError, ValueError):
                    return 0

            if hasattr(tokens_value, "total"):
                return {
                    "input": _to_int(getattr(tokens_value, "input", 0)),
                    "output": _to_int(getattr(tokens_value, "output", 0)),
                    "cache_read": _to_int(getattr(tokens_value, "cache_read", 0)),
                    "cache_write": _to_int(getattr(tokens_value, "cache_write", 0)),
                    "total": _to_int(getattr(tokens_value, "total", 0)),
                }

            if isinstance(tokens_value, dict):
                input_tokens = _to_int(tokens_value.get("input", 0))
                output_tokens = _to_int(tokens_value.get("output", 0))
                cache_read = _to_int(tokens_value.get("cache_read", 0))
                cache_write = _to_int(tokens_value.get("cache_write", 0))
                total = _to_int(
                    tokens_value.get(
                        "total", input_tokens + output_tokens + cache_read + cache_write
                    )
                )
                return {
                    "input": input_tokens,
                    "output": output_tokens,
                    "cache_read": cache_read,
                    "cache_write": cache_write,
                    "total": total,
                }

            total = _to_int(tokens_value)

            return {
                "input": 0,
                "output": 0,
                "cache_read": 0,
                "cache_write": 0,
                "total": total,
            }

        def _to_decimal(cost_value: Any) -> Decimal:
            """Convert a cost value to Decimal safely."""
            if isinstance(cost_value, Decimal):
                return cost_value

            try:
                return Decimal(str(cost_value))
            except (ArithmeticError, ValueError, TypeError):
                return Decimal("0.0")

        # Build bare-model fallbacks so SQLite tool rows (bare model IDs) can
        # still match workflow model breakdown keys that are provider-prefixed,
        # while preserving any agent scope in composite agent::model keys.
        model_breakdown_by_bare: Dict[str, Dict[str, Any]] = {}
        for key, stats in model_breakdown.items():
            if not isinstance(stats, dict):
                continue

            bare_model = self._bare_lookup_key(key)
            bucket = model_breakdown_by_bare.setdefault(
                bare_model,
                {
                    "token_details": {
                        "input": 0,
                        "output": 0,
                        "cache_read": 0,
                        "cache_write": 0,
                        "total": 0,
                    },
                    "files": 0,
                    "cost": Decimal("0.0"),
                },
            )
            details = _extract_token_details(stats.get("tokens"))
            for token_key, token_value in details.items():
                bucket["token_details"][token_key] += token_value
            bucket["files"] += int(stats.get("files", 0) or 0)
            bucket["cost"] += _to_decimal(stats.get("cost", Decimal("0.0")))

        per_model_context_by_bare: Dict[str, Dict[str, Any]] = {}
        for key, context_info in per_model_context.items():
            if isinstance(context_info, dict):
                per_model_context_by_bare.setdefault(
                    self._bare_lookup_key(key), context_info
                )

        per_model_output_rates_by_bare: Dict[str, float] = {}
        for key, rate in per_model_output_rates.items():
            per_model_output_rates_by_bare.setdefault(self._bare_lookup_key(key), rate)

        def get_model_info(model_usage: ModelToolUsage):
            """Return tokens, cost, context usage, and output rate for a model."""
            model_name = model_usage.model_name
            direct_key = self._agent_model_lookup_key(
                model_usage.agent_name, model_name
            )
            bare_key = self._bare_lookup_key(direct_key)

            stats = model_breakdown.get(direct_key) or model_breakdown.get(model_name)
            if isinstance(stats, dict):
                token_details = _extract_token_details(stats.get("tokens"))
                tokens = token_details["total"]
                interactions = int(stats.get("files", 0) or 0)
                cost = _to_decimal(stats.get("cost", Decimal("0.0")))
            else:
                aggregate = model_breakdown_by_bare.get(bare_key)
                if not aggregate and model_usage.agent_name is None:
                    aggregate = model_breakdown_by_bare.get(
                        model_name.split("/", 1)[-1]
                    )
                if aggregate:
                    token_details = aggregate["token_details"]
                    tokens = token_details["total"]
                    interactions = int(aggregate.get("files", 0) or 0)
                    cost = aggregate["cost"]
                else:
                    tokens, token_details, interactions, cost = None, None, None, None

            context_info = per_model_context.get(direct_key) or per_model_context.get(
                model_name
            )
            if not isinstance(context_info, dict):
                context_info = per_model_context_by_bare.get(bare_key, {})
                if not context_info and model_usage.agent_name is None:
                    context_info = per_model_context_by_bare.get(
                        model_name.split("/", 1)[-1], {}
                    )
            context_pct = context_info.get("usage_percentage") if context_info else None
            context_size = context_info.get("context_size") if context_info else None
            context_window = (
                context_info.get("context_window") if context_info else None
            )

            output_rate = per_model_output_rates.get(direct_key)
            if output_rate is None:
                output_rate = per_model_output_rates.get(model_name)
            if output_rate is None:
                output_rate = per_model_output_rates_by_bare.get(bare_key, 0.0)
            if output_rate is None and model_usage.agent_name is None:
                output_rate = per_model_output_rates_by_bare.get(
                    model_name.split("/", 1)[-1], 0.0
                )

            return (
                tokens,
                token_details,
                interactions,
                cost,
                context_pct,
                context_size,
                context_window,
                output_rate,
            )

        left_models = []
        right_models = []
        for i, model_usage in enumerate(tool_stats_by_model):
            if i % 2 == 0:
                left_models.append(model_usage)
            else:
                right_models.append(model_usage)

        left_panels = []
        for model_usage in left_models:
            (
                model_tokens,
                model_token_details,
                model_interactions,
                model_cost,
                context_pct,
                context_size,
                context_window,
                output_rate,
            ) = get_model_info(model_usage)
            left_panels.append(
                self.create_model_tool_panel(
                    model_usage,
                    model_tokens=model_tokens,
                    model_token_details=model_token_details,
                    model_interactions=model_interactions,
                    model_cost=model_cost,
                    context_pct=context_pct,
                    context_size=context_size,
                    context_window=context_window,
                    output_rate=output_rate,
                )
            )

        right_panels = []
        for model_usage in right_models:
            (
                model_tokens,
                model_token_details,
                model_interactions,
                model_cost,
                context_pct,
                context_size,
                context_window,
                output_rate,
            ) = get_model_info(model_usage)
            right_panels.append(
                self.create_model_tool_panel(
                    model_usage,
                    model_tokens=model_tokens,
                    model_token_details=model_token_details,
                    model_interactions=model_interactions,
                    model_cost=model_cost,
                    context_pct=context_pct,
                    context_size=context_size,
                    context_window=context_window,
                    output_rate=output_rate,
                )
            )

        left_column = Layout()
        if left_panels:
            left_column.split_column(*[Layout(p, ratio=1) for p in left_panels])

        right_column = Layout()
        if right_panels:
            right_column.split_column(*[Layout(p, ratio=1) for p in right_panels])

        grid_layout = Layout()
        if left_panels and right_panels:
            grid_layout.split_row(left_column, right_column)
        elif left_panels:
            grid_layout.split_column(left_column)
        elif right_panels:
            grid_layout.split_column(right_column)

        outer_panel = Panel(
            grid_layout,
            title=Text("Tools", style="dashboard.title"),
            title_align="left",
            border_style="dashboard.border",
        )

        return Layout(outer_panel)

    def create_dashboard_layout(
        self,
        session: SessionData,
        recent_file: Optional[Any],
        pricing_data: Dict[str, Any],
        quota: Optional[Decimal] = None,
        per_model_output_rates: Optional[Dict[str, float]] = None,
        per_model_context: Optional[Dict[str, Dict[str, Any]]] = None,
        workflow: Optional[SessionWorkflow] = None,
        tool_stats: Optional[List[ToolUsageStats]] = None,
        tool_stats_by_model: Optional[List[ModelToolUsage]] = None,
        controls_hint: Optional[str] = None,
        burn_rate: float = 0.0,
    ) -> Layout:
        """Create the complete dashboard layout."""
        layout = Layout()

        # Default empty dicts if not provided
        per_model_output_rates = per_model_output_rates or {}
        per_model_context = per_model_context or {}

        # Derive a live activity indicator from the most recent interaction.
        last_activity_seconds = self._recent_activity_seconds(recent_file)
        activity_indicator = self._format_activity_indicator(last_activity_seconds)

        # Use workflow data if available, otherwise use session data
        if workflow and workflow.has_sub_agents:
            # Create panels using workflow totals
            header = self.create_header(
                session, workflow, activity_indicator=activity_indicator
            )
            token_panel = self.create_workflow_token_panel(workflow, recent_file)
            status_panel = self.create_workflow_status_panel(
                workflow, pricing_data, quota
            )
            model_panel = self.create_workflow_model_panel(
                workflow, pricing_data, per_model_output_rates, per_model_context
            )
        else:
            # Create panels using single session data
            header = self.create_header(
                session, activity_indicator=activity_indicator
            )
            token_panel = self.create_token_panel(session, recent_file)
            status_panel = self.create_status_panel(session, pricing_data, quota)
            model_panel = self.create_model_panel(
                session, pricing_data, per_model_output_rates, per_model_context
            )

        recent_file_panel = self.create_recent_file_panel(recent_file)
        burn_rate_panel = self.create_burn_rate_panel(
            burn_rate, per_model_output_rates
        )

        # Determine which tool display to use based on model count
        by_model = tool_stats_by_model or []
        use_grid = len(by_model) > 1

        # Build model breakdown data for passing to tool grid panels
        model_breakdown: Optional[Dict[str, Dict[str, Any]]] = None
        if use_grid:
            if workflow and workflow.has_sub_agents:
                from collections import defaultdict

                model_breakdown = defaultdict(
                    lambda: {
                        "tokens": TokenUsage(),
                        "files": 0,
                        "cost": Decimal("0.0"),
                    }
                )
                for sess in workflow.all_sessions:
                    sess_breakdown = sess.get_agent_model_breakdown(pricing_data)
                    for model, stats in sess_breakdown.items():
                        model_tokens = stats["tokens"]
                        model_breakdown[model]["tokens"].input += model_tokens.input
                        model_breakdown[model]["tokens"].output += model_tokens.output
                        model_breakdown[model][
                            "tokens"
                        ].cache_read += model_tokens.cache_read
                        model_breakdown[model][
                            "tokens"
                        ].cache_write += model_tokens.cache_write
                        model_breakdown[model]["files"] += stats.get("files", 0)
                        model_breakdown[model]["cost"] += stats["cost"]
                model_breakdown = dict(model_breakdown)
            else:
                model_breakdown = session.get_model_breakdown(pricing_data)

        # Initialize variables
        tool_grid_panel: Optional[Layout] = None
        tool_panel: Optional[Panel] = None
        model_ratio = 3
        tool_ratio = 2

        if use_grid:
            tool_grid_panel = self.create_tool_grid_panel(
                by_model,
                model_breakdown=model_breakdown,
                per_model_output_rates=per_model_output_rates,
                per_model_context=per_model_context,
            )
            model_ratio = 2
            tool_ratio = 3
        else:
            flat_tool_stats = tool_stats or []
            if by_model and not tool_stats:
                flat_tool_stats = by_model[0].tool_stats
            tool_panel = self.create_tool_panel(flat_tool_stats)

        # 3-4 section layout: Header, Metrics, Models+Tools, optional Controls (bottom)
        if controls_hint:
            controls_panel = self.create_controls_panel(controls_hint)
            layout.split_column(
                Layout(header, size=3),  # Compact header
                Layout(
                    name="metrics", size=12
                ),  # Tokens + Status + Recent (single row)
                Layout(name="models_tools", minimum_size=4),  # Model + Tool breakdown
                Layout(controls_panel, size=3),  # Persistent keybind visibility
            )
        else:
            layout.split_column(
                Layout(header, size=3),  # Compact header
                Layout(
                    name="metrics", size=12
                ),  # Tokens + Status + Recent (single row)
                Layout(name="models_tools", minimum_size=4),  # Model + Tool breakdown
            )

        # Metrics section: 4-column layout
        # (Tokens 40% | Status 20% | Output Rate 20% | Recent 20%)
        layout["metrics"].split_row(
            Layout(token_panel, ratio=2),  # token data (most content)
            Layout(status_panel, ratio=1),  # cost + time combined
            Layout(burn_rate_panel, ratio=1),  # live output tok/s
            Layout(recent_file_panel, ratio=1),  # recent file info
        )

        # Models + Tools section: Full width to tools when using grid (model info embedded in tool panels)
        if use_grid:
            assert tool_grid_panel is not None
            layout["models_tools"].split_column(tool_grid_panel)
        else:
            assert tool_panel is not None
            layout["models_tools"].split_row(
                Layout(model_panel, ratio=model_ratio),
                Layout(tool_panel, ratio=tool_ratio),
            )

        return layout

    def create_progress_bar(self, percentage: float, width: int = 30) -> str:
        """Create a text-based progress bar."""
        filled = int(width * percentage / 100)
        bar = "█" * filled + "░" * (width - filled)
        return f"[{bar}] {percentage:.1f}%"

    def create_compact_progress_bar(self, percentage: float, width: int = 20) -> str:
        """Create a compact progress bar for space-efficient display."""
        filled = int(width * percentage / 100)
        bar = "█" * filled + "░" * (width - filled)
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
                f"[metric.label]Total:[/metric.label] [metric.cost]{self._fmt_cost(total_cost)}[/metric.cost]\n"
                f"[metric.label]Quota:[/metric.label] [metric.cost]{self._fmt_cost(quota)}[/metric.cost]\n"
                f"[{cost_color}]{progress_bar}[/{cost_color}]"
            )
        else:
            cost_text = (
                f"[dashboard.header]Workflow Cost[/dashboard.header]\n"
                f"[metric.label]Total:[/metric.label] [metric.cost]{self._fmt_cost(total_cost)}[/metric.cost]\n"
                f"[metric.label]No quota configured[/metric.label]"
            )

        return Panel(
            cost_text,
            title=Text("Cost", style="dashboard.title"),
            title_align="left",
            border_style="dashboard.border",
        )

    def create_workflow_model_panel(
        self,
        workflow: SessionWorkflow,
        pricing_data: Dict[str, Any],
        per_model_output_rates: Optional[Dict[str, float]] = None,
        per_model_context: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Panel:
        """Create model usage panel for workflow."""
        from collections import defaultdict

        per_model_output_rates = per_model_output_rates or {}
        per_model_context = per_model_context or {}

        # Aggregate model stats across all sessions
        model_data: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {"tokens": TokenUsage(), "files": 0, "cost": Decimal("0.0")}
        )

        for session in workflow.all_sessions:
            model_breakdown = session.get_agent_model_breakdown(pricing_data)
            for model, stats in model_breakdown.items():
                model_tokens = stats["tokens"]
                model_data[model]["tokens"].input += model_tokens.input
                model_data[model]["tokens"].output += model_tokens.output
                model_data[model]["tokens"].cache_read += model_tokens.cache_read
                model_data[model]["tokens"].cache_write += model_tokens.cache_write
                model_data[model]["files"] += stats.get("files", 0)
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
            agent_name, raw_model = self._split_agent_model_key(model)
            model_name = self._format_agent_model_title(
                agent_name,
                raw_model,
                include_agent=agent_name is not None,
                max_length=38,
            )
            bare_model = self._bare_lookup_key(model)
            token_usage = stats["tokens"]

            # Get context usage for this model
            context_info = per_model_context.get(model) or per_model_context.get(
                bare_model, {}
            )
            context_pct = context_info.get("usage_percentage", 0.0)
            context_bar = self.create_compact_progress_bar(context_pct, 8)
            context_size = context_info.get("context_size")
            context_window = context_info.get("context_window")
            if context_size is not None and context_window is not None:
                context_str = (
                    f"context [metric.value]{context_size:,}[/metric.value]/"
                    f"[metric.value]{context_window:,}[/metric.value] {context_bar}"
                )
            else:
                context_str = f"context {context_bar}"

            # Get output rate for this model
            output_rate = per_model_output_rates.get(
                model, per_model_output_rates.get(bare_model, 0.0)
            )
            rate_str = f" - {output_rate:.1f} tok/s" if output_rate > 0 else ""

            model_lines.append(
                f"[metric.label]{model_name}[/metric.label]\n"
                f"  └─ Tokens: [metric.value]{token_usage.total:,}[/metric.value] tok "
                f"([metric.label]In:[/metric.label] [metric.value]{token_usage.input:,}[/metric.value] | "
                f"[metric.label]Out:[/metric.label] [metric.value]{token_usage.output:,}[/metric.value] | "
                f"[metric.label]CW:[/metric.label] [metric.value]{token_usage.cache_write:,}[/metric.value] | "
                f"[metric.label]CR:[/metric.label] [metric.value]{token_usage.cache_read:,}[/metric.value])\n"
                f"  └─ Interactions: [metric.value]{stats['files']:,}[/metric.value]  -  "
                f"Cost: [metric.cost]{self._fmt_cost(stats['cost'])}[/metric.cost]  -  "
                f"{context_str}{rate_str}"
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
