"""Tool usage models for OpenCode Monitor."""

from typing import List
from pydantic import BaseModel, computed_field


class ToolUsageStats(BaseModel):
    """Statistics for a single tool's usage."""
    tool_name: str
    total_calls: int = 0
    success_count: int = 0
    failure_count: int = 0

    @computed_field
    @property
    def success_rate(self) -> float:
        """Calculate success rate as percentage."""
        if self.total_calls == 0:
            return 0.0
        return (self.success_count / self.total_calls) * 100.0


class ToolUsageSummary(BaseModel):
    """Summary of all tool usage across sessions."""
    tool_stats: List[ToolUsageStats] = []

    @computed_field
    @property
    def total_calls(self) -> int:
        """Total calls across all tools."""
        return sum(t.total_calls for t in self.tool_stats)

    @computed_field
    @property
    def total_success(self) -> int:
        """Total successful calls across all tools."""
        return sum(t.success_count for t in self.tool_stats)

    @computed_field
    @property
    def total_failures(self) -> int:
        """Total failed calls across all tools."""
        return sum(t.failure_count for t in self.tool_stats)

    @computed_field
    @property
    def overall_success_rate(self) -> float:
        """Overall success rate across all tools."""
        if self.total_calls == 0:
            return 0.0
        return (self.total_success / self.total_calls) * 100.0


class ModelToolUsage(BaseModel):
    """Tool usage statistics grouped by model."""
    model_name: str
    tool_stats: List[ToolUsageStats] = []

    @computed_field
    @property
    def total_calls(self) -> int:
        """Total tool calls for this model."""
        return sum(t.total_calls for t in self.tool_stats)
