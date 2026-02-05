"""Workflow models for grouping related sessions."""

from datetime import datetime
from typing import List, Optional
from decimal import Decimal
from pydantic import BaseModel, computed_field

from .session import SessionData, TokenUsage


class SessionWorkflow(BaseModel):
    """Represents a group of related sessions (main + sub-agents)."""

    workflow_id: str  # Same as main session ID
    main_session: SessionData
    sub_agent_sessions: List[SessionData] = []

    @computed_field
    @property
    def project_name(self) -> str:
        """Get project name from main session."""
        return self.main_session.project_name

    @computed_field
    @property
    def start_time(self) -> Optional[datetime]:
        """Get earliest start time across all sessions."""
        times = [self.main_session.start_time] + [s.start_time for s in self.sub_agent_sessions]
        valid_times = [t for t in times if t is not None]
        return min(valid_times) if valid_times else None

    @computed_field
    @property
    def end_time(self) -> Optional[datetime]:
        """Get latest end time across all sessions."""
        times = [self.main_session.end_time] + [s.end_time for s in self.sub_agent_sessions]
        valid_times = [t for t in times if t is not None]
        return max(valid_times) if valid_times else None

    @computed_field
    @property
    def total_tokens(self) -> TokenUsage:
        """Aggregate tokens across main + all sub-agents."""
        all_sessions = [self.main_session] + self.sub_agent_sessions
        return TokenUsage(
            input=sum(s.total_tokens.input for s in all_sessions),
            output=sum(s.total_tokens.output for s in all_sessions),
            cache_read=sum(s.total_tokens.cache_read for s in all_sessions),
            cache_write=sum(s.total_tokens.cache_write for s in all_sessions),
        )

    @computed_field
    @property
    def total_cost(self) -> Decimal:
        """Placeholder for total cost - actual calculation requires pricing data."""
        # Note: Actual cost calculation happens in report generator with pricing data
        return Decimal('0.0')

    @computed_field
    @property
    def session_count(self) -> int:
        """Get total number of sessions in workflow."""
        return 1 + len(self.sub_agent_sessions)

    @property
    def all_sessions(self) -> List[SessionData]:
        """Get all sessions (main + sub-agents) in chronological order."""
        all_sess = [self.main_session] + self.sub_agent_sessions
        return sorted(all_sess, key=lambda s: s.start_time or datetime.min)

    @property
    def session_title(self) -> str:
        """Use main session's title for the workflow."""
        return self.main_session.session_title or ""

    @property
    def display_title(self) -> str:
        """Get display-friendly workflow title."""
        return self.main_session.display_title

    def calculate_total_cost(self, pricing_data: dict) -> Decimal:
        """Calculate aggregate cost across all sessions.

        Args:
            pricing_data: Dictionary of model pricing information

        Returns:
            Total cost in USD
        """
        all_sessions = [self.main_session] + self.sub_agent_sessions
        return sum(s.calculate_total_cost(pricing_data) for s in all_sessions)

    @computed_field
    @property
    def has_sub_agents(self) -> bool:
        """Check if workflow has any sub-agent sessions."""
        return len(self.sub_agent_sessions) > 0

    @computed_field
    @property
    def sub_agent_count(self) -> int:
        """Get number of sub-agent sessions."""
        return len(self.sub_agent_sessions)
