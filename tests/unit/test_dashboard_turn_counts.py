from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast

from ocmonitor.models.session import TokenUsage
from ocmonitor.models.tool_usage import ModelToolUsage
from ocmonitor.ui.dashboard import DashboardUI


def _workflow_panel(turn_counts):
    session = SimpleNamespace(
        get_agent_model_breakdown=lambda pricing: {
            "agent/model": {
                "tokens": TokenUsage(input=10, output=5),
                "files": 3,
                "cost": Decimal("0.25"),
            }
        }
    )
    workflow = SimpleNamespace(all_sessions=[session])
    return DashboardUI().create_workflow_model_panel(
        cast(Any, workflow),
        pricing_data={},
        completed_turn_counts=turn_counts,
    ).renderable.__str__()


def test_workflow_model_panel_shows_counts_and_preserves_interactions():
    panel_text = _workflow_panel({"build": 12, "test": 0})

    assert "Completed stored prompts by agent:" in panel_text
    assert "build: 12, test: 0" in panel_text
    assert "Interactions:" in panel_text
    assert "3" in panel_text


def test_workflow_model_panel_shows_unavailable_when_counts_are_unknown():
    panel_text = _workflow_panel(None)

    assert "Completed stored prompts by agent:" in panel_text
    assert "Unavailable" in panel_text
    assert "Database-validated stored prompts with completed responses" in panel_text


def test_workflow_model_panel_shows_turn_counts_without_model_data():
    workflow = SimpleNamespace(all_sessions=[])
    panel_text = DashboardUI().create_workflow_model_panel(
        cast(Any, workflow),
        pricing_data={},
        completed_turn_counts={"build": 0},
    ).renderable.__str__()

    assert "Completed stored prompts by agent:" in panel_text
    assert "build: 0" in panel_text
    assert "No model data available" in panel_text


def _dashboard_layout(turn_counts, grid):
    model_stats = [
        ModelToolUsage(model_name="model-a"),
        ModelToolUsage(model_name="model-b"),
    ] if grid else []
    session = SimpleNamespace(
        start_time=None,
        end_time=None,
        session_title="test",
        display_title="test",
        project_name="project",
        tokens=TokenUsage(input=10, output=5),
        total_tokens=TokenUsage(input=10, output=5),
        interaction_count=1,
        calculate_total_cost=lambda pricing: Decimal("0"),
        duration_hours=0,
        duration_percentage=0,
        total_processing_time_ms=0,
        get_model_breakdown=lambda pricing: {
            "model-a": {
                "tokens": TokenUsage(input=10, output=5),
                "cost": Decimal("0.25"),
            }
        },
    )
    layout = DashboardUI().create_dashboard_layout(
        cast(Any, session),
        recent_file=None,
        pricing_data={},
        tool_stats_by_model=model_stats,
        completed_turn_counts=turn_counts,
    )
    return layout


def _render(layout):
    from rich.console import Console
    from io import StringIO
    from ocmonitor.ui.theme import get_theme

    output = StringIO()
    Console(file=output, width=160, theme=get_theme()).print(layout)
    return output.getvalue()


def test_dashboard_layout_displays_turn_summary_in_grid_without_model_panel():
    rendered = _render(_dashboard_layout({"z-agent": 2, "a-agent": 0}, grid=True))

    assert "Completed stored prompts by agent:" in rendered
    assert "a-agent: 0, z-agent: 2" in rendered
    assert rendered.count("Completed stored prompts by agent:") == 1


def test_dashboard_layout_displays_turn_summary_once_in_non_grid_model_panel():
    rendered = _render(_dashboard_layout({}, grid=False))

    assert "Completed stored prompts by agent:" in rendered
    assert "None" in rendered
    assert rendered.count("Completed stored prompts by agent:") == 1


def test_dashboard_layout_renders_agent_markup_as_literal_text():
    agent = "[red]injected[/red]"
    layout = _dashboard_layout({agent: 7}, grid=True)

    rendered = _render(layout)

    assert f"{agent}: 7" in rendered
    assert "\x1b[31m" not in rendered
