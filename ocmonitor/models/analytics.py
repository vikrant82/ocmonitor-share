"""Analytics data models for OpenCode Monitor."""

import statistics
from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional, Set
from decimal import Decimal
from pydantic import BaseModel, Field, computed_field
from collections import defaultdict
from .session import SessionData, TokenUsage, InteractionFile
from .tool_usage import ToolUsageStats, ToolUsageSummary


class DailyUsage(BaseModel):
    """Model for daily usage statistics."""
    date: date
    sessions: List[SessionData] = Field(default_factory=list)

    @computed_field
    @property
    def total_tokens(self) -> TokenUsage:
        """Calculate total tokens for the day."""
        total = TokenUsage()
        for session in self.sessions:
            session_tokens = session.total_tokens
            total.input += session_tokens.input
            total.output += session_tokens.output
            total.cache_write += session_tokens.cache_write
            total.cache_read += session_tokens.cache_read
        return total

    @computed_field
    @property
    def total_interactions(self) -> int:
        """Calculate total interactions for the day."""
        return sum(session.interaction_count for session in self.sessions)

    @computed_field
    @property
    def models_used(self) -> List[str]:
        """Get unique models used on this day."""
        models = set()
        for session in self.sessions:
            models.update(session.models_used)
        return list(models)

    def calculate_total_cost(self, pricing_data: Dict[str, Any], force_recalculate: bool = False) -> Decimal:
        """Calculate total cost for the day.

        Args:
            pricing_data: Dictionary of model pricing information
            force_recalculate: If True, ignore stored costs and recalculate from pricing data
        """
        return sum((session.calculate_total_cost(pricing_data, force_recalculate) for session in self.sessions), Decimal('0.0'))


class WeeklyUsage(BaseModel):
    """Model for weekly usage statistics."""
    year: int
    week: int
    start_date: date
    end_date: date
    daily_usage: List[DailyUsage] = Field(default_factory=list)

    @computed_field
    @property
    def total_tokens(self) -> TokenUsage:
        """Calculate total tokens for the week."""
        total = TokenUsage()
        for day in self.daily_usage:
            day_tokens = day.total_tokens
            total.input += day_tokens.input
            total.output += day_tokens.output
            total.cache_write += day_tokens.cache_write
            total.cache_read += day_tokens.cache_read
        return total

    @computed_field
    @property
    def total_sessions(self) -> int:
        """Calculate total sessions for the week."""
        session_ids = {
            session.session_id
            for day in self.daily_usage
            for session in day.sessions
        }
        return len(session_ids)

    @computed_field
    @property
    def total_interactions(self) -> int:
        """Calculate total interactions for the week."""
        return sum(day.total_interactions for day in self.daily_usage)

    def calculate_total_cost(self, pricing_data: Dict[str, Any], force_recalculate: bool = False) -> Decimal:
        """Calculate total cost for the week.

        Args:
            pricing_data: Dictionary of model pricing information
            force_recalculate: If True, ignore stored costs and recalculate from pricing data
        """
        return sum((day.calculate_total_cost(pricing_data, force_recalculate) for day in self.daily_usage), Decimal('0.0'))


class MonthlyUsage(BaseModel):
    """Model for monthly usage statistics."""
    year: int
    month: int
    weekly_usage: List[WeeklyUsage] = Field(default_factory=list)

    @computed_field
    @property
    def total_tokens(self) -> TokenUsage:
        """Calculate total tokens for the month."""
        total = TokenUsage()
        for week in self.weekly_usage:
            week_tokens = week.total_tokens
            total.input += week_tokens.input
            total.output += week_tokens.output
            total.cache_write += week_tokens.cache_write
            total.cache_read += week_tokens.cache_read
        return total

    @computed_field
    @property
    def total_sessions(self) -> int:
        """Calculate total sessions for the month."""
        session_ids = {
            session.session_id
            for week in self.weekly_usage
            for day in week.daily_usage
            for session in day.sessions
        }
        return len(session_ids)

    @computed_field
    @property
    def total_interactions(self) -> int:
        """Calculate total interactions for the month."""
        return sum(week.total_interactions for week in self.weekly_usage)

    def calculate_total_cost(self, pricing_data: Dict[str, Any], force_recalculate: bool = False) -> Decimal:
        """Calculate total cost for the month.

        Args:
            pricing_data: Dictionary of model pricing information
            force_recalculate: If True, ignore stored costs and recalculate from pricing data
        """
        return sum((week.calculate_total_cost(pricing_data, force_recalculate) for week in self.weekly_usage), Decimal('0.0'))


class ModelUsageStats(BaseModel):
    """Model for model-specific usage statistics."""
    display_model: str
    total_tokens: TokenUsage = Field(default_factory=TokenUsage)
    total_sessions: int = Field(default=0)
    total_interactions: int = Field(default=0)
    total_cost: Decimal = Field(default=Decimal('0.0'))
    total_duration_ms: int = Field(default=0, description="Total processing time in milliseconds")
    interaction_rates: List[float] = Field(default_factory=list, description="Per-interaction output rates for eligible interactions")
    first_used: Optional[datetime] = Field(default=None)
    last_used: Optional[datetime] = Field(default=None)

    @computed_field
    @property
    def p50_output_rate(self) -> float:
        """Calculate median (p50) output tokens per second from eligible interactions."""
        if not self.interaction_rates:
            return 0.0
        return statistics.median(self.interaction_rates)


class ModelBreakdownReport(BaseModel):
    """Model for model usage breakdown report."""
    timeframe: str  # "daily", "weekly", "monthly", "all"
    start_date: Optional[date] = Field(default=None)
    end_date: Optional[date] = Field(default=None)
    model_stats: List[ModelUsageStats] = Field(default_factory=list)

    @computed_field
    @property
    def total_cost(self) -> Decimal:
        """Calculate total cost across all models."""
        return sum((model.total_cost for model in self.model_stats), Decimal('0.0'))

    @computed_field
    @property
    def total_tokens(self) -> TokenUsage:
        """Calculate total tokens across all models."""
        total = TokenUsage()
        for model in self.model_stats:
            total.input += model.total_tokens.input
            total.output += model.total_tokens.output
            total.cache_write += model.total_tokens.cache_write
            total.cache_read += model.total_tokens.cache_read
        return total


class ModelDetailStats(BaseModel):
    """Detailed statistics for a single model."""
    model_name: str
    first_used: Optional[datetime] = None
    last_used: Optional[datetime] = None
    total_sessions: int = 0
    total_days_used: int = 0
    total_interactions: int = 0
    total_tokens: TokenUsage = Field(default_factory=TokenUsage)
    total_cost: Decimal = Field(default=Decimal('0.0'))
    avg_cost_per_day: Decimal = Field(default=Decimal('0.0'))
    avg_cost_per_session: Decimal = Field(default=Decimal('0.0'))
    interaction_rates: List[float] = Field(default_factory=list)
    tool_stats: List[ToolUsageStats] = Field(default_factory=list)
    tool_summary: ToolUsageSummary = Field(default_factory=ToolUsageSummary)

    @computed_field
    @property
    def p50_output_rate(self) -> float:
        """Calculate median (p50) output tokens per second from eligible interactions."""
        if not self.interaction_rates:
            return 0.0
        return statistics.median(self.interaction_rates)


class ProjectUsageStats(BaseModel):
    """Model for project-specific usage statistics."""
    project_name: str
    total_tokens: TokenUsage = Field(default_factory=TokenUsage)
    total_sessions: int = Field(default=0)
    total_interactions: int = Field(default=0)
    total_cost: Decimal = Field(default=Decimal('0.0'))
    models_used: List[str] = Field(default_factory=list)
    first_activity: Optional[datetime] = Field(default=None)
    last_activity: Optional[datetime] = Field(default=None)


class ProjectBreakdownReport(BaseModel):
    """Model for project usage breakdown report."""
    timeframe: str  # "daily", "weekly", "monthly", "all"
    start_date: Optional[date] = Field(default=None)
    end_date: Optional[date] = Field(default=None)
    project_stats: List[ProjectUsageStats] = Field(default_factory=list)

    @computed_field
    @property
    def total_cost(self) -> Decimal:
        """Calculate total cost across all projects."""
        total: Decimal = Decimal('0.0')
        for project in self.project_stats:
            total += project.total_cost
        return total

    @computed_field
    @property
    def total_tokens(self) -> TokenUsage:
        """Calculate total tokens across all projects."""
        total = TokenUsage()
        for project in self.project_stats:
            total.input += project.total_tokens.input
            total.output += project.total_tokens.output
            total.cache_write += project.total_tokens.cache_write
            total.cache_read += project.total_tokens.cache_read
        return total


class TimeframeAnalyzer:
    """Analyzer for different timeframe breakdowns."""

    @staticmethod
    def _interaction_date(file: InteractionFile, fallback_date: Optional[date]) -> Optional[date]:
        """Return interaction date using interaction timestamp with fallback."""
        if file.time_data and file.time_data.created_datetime:
            return file.time_data.created_datetime.date()
        return fallback_date

    @staticmethod
    def _is_in_date_range(
        check_date: Optional[date],
        start_date: Optional[date],
        end_date: Optional[date],
    ) -> bool:
        """Check whether a date is within optional inclusive bounds."""
        if check_date is None:
            return False
        if start_date and check_date < start_date:
            return False
        if end_date and check_date > end_date:
            return False
        return True

    @staticmethod
    def create_daily_breakdown(sessions: List[SessionData]) -> List[DailyUsage]:
        """Create daily breakdown from sessions."""
        daily_data = defaultdict(lambda: defaultdict(list))
        session_refs: Dict[int, SessionData] = {}

        for session in sessions:
            session_key = id(session)
            session_refs[session_key] = session
            fallback_date = session.start_time.date() if session.start_time else None

            for file in session.files:
                interaction_date = TimeframeAnalyzer._interaction_date(file, fallback_date)
                if interaction_date is None:
                    continue
                daily_data[interaction_date][session_key].append(file)

        daily_usage = []
        for date_key, sessions_files in sorted(daily_data.items()):
            sessions_list = [
                session_refs[session_key].model_copy(update={"files": files})
                for session_key, files in sessions_files.items()
            ]
            daily_usage.append(DailyUsage(date=date_key, sessions=sessions_list))

        return daily_usage

    @staticmethod
    def create_weekly_breakdown(daily_usage: List[DailyUsage], week_start_day: int = 0) -> List[WeeklyUsage]:
        """Create weekly breakdown from daily usage.
        
        Args:
            daily_usage: List of daily usage records
            week_start_day: Day to start week on (0=Monday, 6=Sunday)
        
        Returns:
            List of WeeklyUsage objects
        """
        from ..utils.time_utils import TimeUtils
        
        weekly_data = defaultdict(list)

        for day in daily_usage:
            # Get the week start date for this day
            week_start, week_end = TimeUtils.get_custom_week_range(day.date, week_start_day)
            
            # Use (week_start, week_end) tuple as key for grouping
            week_key = (week_start, week_end)
            weekly_data[week_key].append(day)

        weekly_breakdown = []
        for (week_start, week_end), days in sorted(weekly_data.items()):
            # For display purposes, calculate ISO week number for the week_start
            year, week, _ = week_start.isocalendar()
            
            weekly_breakdown.append(WeeklyUsage(
                year=year,
                week=week,
                start_date=week_start,
                end_date=week_end,
                daily_usage=sorted(days, key=lambda d: d.date)
            ))

        return weekly_breakdown

    @staticmethod
    def create_monthly_breakdown(weekly_usage: List[WeeklyUsage]) -> List[MonthlyUsage]:
        """Create monthly breakdown from weekly usage."""
        monthly_data = defaultdict(list)

        for week in weekly_usage:
            # Assign week to month based on start date
            month_key = (week.start_date.year, week.start_date.month)
            monthly_data[month_key].append(week)

        return [
            MonthlyUsage(year=year, month=month, weekly_usage=weeks)
            for (year, month), weeks in sorted(monthly_data.items())
        ]

    @staticmethod
    def create_model_breakdown(
        sessions: List[SessionData],
        pricing_data: Dict[str, Any],
        timeframe: str = "all",
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        force_recalculate: bool = False,
    ) -> ModelBreakdownReport:
        """Create model usage breakdown."""
        from typing import Dict, Set
        
        # Define model stats structure with proper types
        class ModelStats:
            """Accumulator for per-model aggregates during report creation."""

            def __init__(self):
                """Initialize aggregate fields for a model bucket."""
                self.tokens = TokenUsage()
                self.sessions: Set[str] = set()
                self.interactions = 0
                self.cost = Decimal('0.0')
                self.duration_ms = 0
                self.interaction_rates: List[float] = []
                self.first_used: Optional[datetime] = None
                self.last_used: Optional[datetime] = None
        
        model_data: Dict[str, ModelStats] = defaultdict(ModelStats)

        for session in sessions:
            if start_date or end_date:
                fallback_date = session.start_time.date() if session.start_time else None
                filtered_files = [
                    file
                    for file in session.files
                    if TimeframeAnalyzer._is_in_date_range(
                        TimeframeAnalyzer._interaction_date(file, fallback_date),
                        start_date,
                        end_date,
                    )
                ]
            else:
                filtered_files = list(session.files)

            if not filtered_files:
                continue

            for display_model in {file.display_model for file in filtered_files}:
                model_files = [f for f in filtered_files if f.display_model == display_model]
                model_stats = model_data[display_model]

                # Update token counts
                for file in model_files:
                    model_stats.tokens.input += file.tokens.input
                    model_stats.tokens.output += file.tokens.output
                    model_stats.tokens.cache_write += file.tokens.cache_write
                    model_stats.tokens.cache_read += file.tokens.cache_read
                    model_stats.interactions += 1
                    model_stats.cost += file.calculate_cost(pricing_data, force_recalculate)
                    # Track processing duration
                    if file.time_data and file.time_data.duration_ms:
                        model_stats.duration_ms += file.time_data.duration_ms
                    # Collect per-interaction rates for eligible files
                    if file.is_rate_eligible:
                        rate = file.tokens.output / (file.time_data.duration_ms / 1000)
                        model_stats.interaction_rates.append(rate)

                # Track sessions
                model_stats.sessions.add(session.session_id)

                # Update first/last used times
                model_start_times = [
                    file.time_data.created_datetime
                    for file in model_files
                    if file.time_data and file.time_data.created_datetime
                ]
                model_end_times = [
                    file.time_data.completed_datetime
                    for file in model_files
                    if file.time_data and file.time_data.completed_datetime
                ]

                model_first = min(model_start_times) if model_start_times else (
                    session.start_time if model_files else None
                )
                model_last = max(model_end_times) if model_end_times else (
                    session.start_time if model_files else None
                )

                if model_first:
                    if model_stats.first_used is None or model_first < model_stats.first_used:
                        model_stats.first_used = model_first

                if model_last:
                    if model_stats.last_used is None or model_last > model_stats.last_used:
                        model_stats.last_used = model_last

        # Convert to ModelUsageStats objects
        model_stats_list = []
        for display_model, stats in model_data.items():
            model_stats_list.append(ModelUsageStats(
                display_model=display_model,
                total_tokens=stats.tokens,
                total_sessions=len(stats.sessions),
                total_interactions=stats.interactions,
                total_cost=stats.cost,
                total_duration_ms=stats.duration_ms,
                interaction_rates=stats.interaction_rates,
                first_used=stats.first_used,
                last_used=stats.last_used
            ))

        # Sort by total cost descending
        model_stats_list.sort(key=lambda x: x.total_cost, reverse=True)

        return ModelBreakdownReport(
            timeframe=timeframe,
            start_date=start_date,
            end_date=end_date,
            model_stats=model_stats_list
        )

    @staticmethod
    def create_project_breakdown(
        sessions: List[SessionData],
        pricing_data: Dict[str, Any],
        timeframe: str = "all",
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        force_recalculate: bool = False,
    ) -> 'ProjectBreakdownReport':
        """Create project usage breakdown."""
        # Define project stats structure with proper types
        class ProjectStats:
            """Accumulator for per-project aggregates during report creation."""

            def __init__(self):
                """Initialize aggregate fields for a project bucket."""
                self.tokens = TokenUsage()
                self.sessions: Set[str] = set()
                self.interactions = 0
                self.cost = Decimal('0.0')
                self.models_used: Set[str] = set()
                self.first_activity: Optional[datetime] = None
                self.last_activity: Optional[datetime] = None
        
        project_data: Dict[str, ProjectStats] = defaultdict(ProjectStats)

        for session in sessions:
            if start_date or end_date:
                fallback_date = session.start_time.date() if session.start_time else None
                filtered_files = [
                    file
                    for file in session.files
                    if TimeframeAnalyzer._is_in_date_range(
                        TimeframeAnalyzer._interaction_date(file, fallback_date),
                        start_date,
                        end_date,
                    )
                ]
            else:
                filtered_files = list(session.files)

            if not filtered_files:
                continue

            project_files: Dict[str, List[InteractionFile]] = defaultdict(list)
            for file in filtered_files:
                project_files[file.project_name].append(file)

            for project_name, files in project_files.items():
                project_stats = project_data[project_name]

                for file in files:
                    project_stats.tokens.input += file.tokens.input
                    project_stats.tokens.output += file.tokens.output
                    project_stats.tokens.cache_write += file.tokens.cache_write
                    project_stats.tokens.cache_read += file.tokens.cache_read

                project_stats.sessions.add(session.session_id)
                project_stats.interactions += len(files)
                project_stats.cost += sum(
                    (file.calculate_cost(pricing_data, force_recalculate) for file in files),
                    Decimal('0.0'),
                )
                project_stats.models_used.update(file.display_model for file in files)

                session_start_times = [
                    file.time_data.created_datetime
                    for file in files
                    if file.time_data and file.time_data.created_datetime
                ]
                session_end_times = [
                    file.time_data.completed_datetime
                    for file in files
                    if file.time_data and file.time_data.completed_datetime
                ]

                session_first = min(session_start_times) if session_start_times else (
                    session.start_time if files else None
                )
                session_last = max(session_end_times) if session_end_times else (
                    session.start_time if files else None
                )

                if session_first:
                    if (project_stats.first_activity is None or
                        session_first < project_stats.first_activity):
                        project_stats.first_activity = session_first

                if session_last:
                    if (project_stats.last_activity is None or
                        session_last > project_stats.last_activity):
                        project_stats.last_activity = session_last

        # Convert to ProjectUsageStats objects
        project_stats = []
        for project_name, stats in project_data.items():
            project_stats.append(ProjectUsageStats(
                project_name=project_name,
                total_tokens=stats.tokens,
                total_sessions=len(stats.sessions),
                total_interactions=stats.interactions,
                total_cost=stats.cost,
                models_used=list(stats.models_used),
                first_activity=stats.first_activity,
                last_activity=stats.last_activity
            ))

        # Sort by total cost descending
        project_stats.sort(key=lambda x: x.total_cost, reverse=True)

        return ProjectBreakdownReport(
            timeframe=timeframe,
            start_date=start_date,
            end_date=end_date,
            project_stats=project_stats
        )
