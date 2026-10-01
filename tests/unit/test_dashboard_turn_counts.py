"""Completed stored prompt counts stay separate from interaction counts."""

from io import StringIO
from pathlib import Path
from typing import Optional

import pytest
from rich.console import Console

from ocmonitor.models.session import InteractionFile, SessionData, TokenUsage
from ocmonitor.models.tool_usage import ModelToolUsage
from ocmonitor.models.workflow import SessionWorkflow
from ocmonitor.ui.dashboard import DashboardUI
from ocmonitor.ui.theme import get_theme


def _session(agent: Optional[str] = "build"):
    return SessionData(
        session_id="main",
        session_title="Prompt counts",
        files=[InteractionFile(
            file_path=Path(f"/nonexistent/{index}.json"),
            session_id="main", model_id="model-a", agent=agent,
            tokens=TokenUsage(input=10, output=5), raw_data={"cost": 0.25},
        ) for index in range(3)],
    )


def _render(renderable):
    output = StringIO()
    Console(file=output, width=220, height=60, theme=get_theme(), color_system=None).print(renderable)
    return output.getvalue()


@pytest.mark.parametrize("workflow", [False, True])
@pytest.mark.parametrize("counts, expected", [
    (None, "N/A"), ({}, "0"), ({"other": 12}, "0"), ({"build": 12}, "12"),
])
def test_model_rows_use_validated_counts_not_interactions(workflow, counts, expected):
    session = _session()
    ui = DashboardUI()
    if workflow:
        panel = ui.create_workflow_model_panel(
            SessionWorkflow(workflow_id="main", main_session=session), {},
            completed_turn_counts=counts,
        )
    else:
        panel = ui.create_model_panel(session, {}, completed_turn_counts=counts)

    text = _render(panel)

    assert f"Completed prompts: {expected} | Cache Hit: 0.0%" in text
    assert text.count("Completed prompts:") == 1
    assert "Tokens: 45 tok" in text
    assert "Cost: $0.75" in text
    if workflow:
        assert "Interactions: 3" in text


@pytest.mark.parametrize("counts, expected", [
    (None, "N/A"), ({}, "0"), ({"other": 12}, "0"), ({"main": 7}, "7"),
])
def test_grid_missing_agent_uses_main_counts_without_tool_activity(counts, expected):
    session = _session(agent=None)
    text = _render(DashboardUI().create_dashboard_layout(
        session, None, {},
        tool_stats_by_model=[ModelToolUsage(model_name="model-a"), ModelToolUsage(model_name="model-b")],
        completed_turn_counts=counts,
    ))

    assert text.count(f"Completed prompts: {expected} | Cache Hit: 0.0%") == 2
    assert text.count("No tool activity") == 2
    assert "Tokens: 45 total" in text
    assert "Cost $0.75" in text


@pytest.mark.parametrize("workflow", [False, True])
def test_counts_without_model_data_do_not_invent_agent_sections(workflow):
    session = SessionData(session_id="main", files=[])
    ui = DashboardUI()
    if workflow:
        panel = ui.create_workflow_model_panel(
            SessionWorkflow(workflow_id="main", main_session=session), {},
            completed_turn_counts={"build": 12},
        )
    else:
        panel = ui.create_model_panel(session, {}, completed_turn_counts={"build": 12})

    text = _render(panel)

    assert "No model data available" in text
    assert "Completed prompts:" not in text
    assert "build" not in text
    assert "Completed stored prompts by agent:" not in text


@pytest.mark.parametrize("grid", [False, True])
def test_dashboard_renders_agent_markup_as_literal_text(grid):
    agent = "[red]injected[/red]"
    session = _session(agent)
    model_stats = [ModelToolUsage(model_name="model-a", agent_name=agent),
                   ModelToolUsage(model_name="model-b", agent_name=agent)] if grid else []
    text = _render(DashboardUI().create_dashboard_layout(
        session, None, {}, tool_stats_by_model=model_stats,
        completed_turn_counts={agent: 7},
    ))

    assert agent in text
    assert "Completed prompts: 7 | Cache Hit: 0.0%" in text
    assert "\x1b[31m" not in text
