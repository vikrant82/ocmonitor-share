"""Behavioral rendering checks for cumulative prompt-cache hit percentages."""

from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console

from ocmonitor.models.session import InteractionFile, SessionData, TokenUsage
from ocmonitor.models.tool_usage import ModelToolUsage, ToolUsageStats
from ocmonitor.models.workflow import SessionWorkflow
from ocmonitor.ui.dashboard import DashboardUI
from ocmonitor.ui.theme import get_theme


def _interaction(session_id, model, agent, usage):
    return InteractionFile(
        file_path=Path(f"/nonexistent/{session_id}-{model}.json"),
        session_id=session_id,
        model_id=model,
        agent=agent,
        tokens=TokenUsage(**usage),
        raw_data={"cost": 0.25},
    )


def _session(session_id, rows):
    return SessionData(
        session_id=session_id,
        session_title="Cache rendering",
        agent="session-only-agent",
        files=[_interaction(session_id, *row) for row in rows],
    )


@pytest.fixture
def render():
    output = StringIO()
    console = Console(
        file=output, width=220, height=60, theme=get_theme(), color_system=None
    )
    ui = DashboardUI(console=console)

    def capture(renderable):
        output.seek(0)
        output.truncate()
        console.print(renderable)
        return output.getvalue()

    return ui, capture


@pytest.mark.parametrize("workflow", [False, True], ids=["session", "workflow"])
@pytest.mark.parametrize("recent", [False, True], ids=["no-recent", "recent"])
@pytest.mark.parametrize(
    "usage, expected",
    [
        ({"input": 20, "cache_read": 60, "cache_write": 20, "output": 900}, "60.0%"),
        ({"input": 10, "output": 900}, "0.0%"),
        ({"cache_read": 10, "output": 900}, "100.0%"),
        ({"output": 900}, "N/A"),
    ],
)
def test_token_panel_shows_cumulative_prompt_cache_hit(render, workflow, recent, usage, expected):
    ui, capture = render
    session = _session("main", [("model-a", None, usage)])
    # A recent interaction with a different hit rate must not replace totals.
    recent_file = _interaction("recent", "latest", None, {"input": 7}) if recent else None
    if workflow:
        group = SessionWorkflow(workflow_id="main", main_session=session)
        panel = ui.create_workflow_token_panel(group, recent_file)
    else:
        panel = ui.create_token_panel(session, recent_file)

    text = capture(panel)

    assert f"Cache Hit: {expected}" in text
    assert text.count("Cache Hit:") == 1
    assert "Total:" in text
    assert "900" in text


@pytest.fixture
def mixed_workflow():
    main = _session("main", [
        ("model-a", "build", {"input": 10, "cache_read": 90, "output": 1000}),
        ("model-b", "build", {"input": 300, "cache_read": 100, "cache_write": 100}),
        ("model-a", None, {"input": 10, "cache_read": 10}),
    ])
    child = _session("child", [
        ("model-c", "build", {"input": 100, "cache_read": 100, "cache_write": 100}),
        ("model-b", "main", {"input": 30, "cache_read": 10, "cache_write": 20}),
        ("model-c", "empty", {"output": 30}),
    ])
    return SessionWorkflow(workflow_id="main", main_session=main, sub_agent_sessions=[child])


@pytest.mark.parametrize("recent", [False, True])
def test_workflow_cache_hit_is_weighted_by_aggregate_prompt_tokens(render, mixed_workflow, recent):
    ui, capture = render
    recent_file = mixed_workflow.main_session.files[0] if recent else None

    text = capture(ui.create_workflow_token_panel(mixed_workflow, recent_file))

    # 310 cached reads / 980 prompt tokens, not the mean of session rates.
    assert "Cache Hit: 31.6%" in text
    assert "Workflow Totals" in text
    assert "Total: 2,010" in text


@pytest.mark.parametrize("workflow", [False, True], ids=["session", "workflow"])
def test_model_panel_groups_cache_hits_by_agent_across_models(render, mixed_workflow, workflow):
    ui, capture = render
    if workflow:
        panel = ui.create_workflow_model_panel(mixed_workflow, {}, completed_turn_counts={"build": 2})
        expected = "32.2%"
    else:
        panel = ui.create_model_panel(mixed_workflow.main_session, {}, completed_turn_counts={"build": 2})
        expected = "31.7%"

    text = capture(panel)

    # build: 190/600 in one session; 290/900 across both sessions.
    assert text.count(f"Completed prompts: 2 | Cache Hit: {expected}") == (3 if workflow else 2)
    main_rate = "25.0%" if workflow else "50.0%"
    assert f"Completed prompts: 0 | Cache Hit: {main_rate}" in text
    if workflow:
        assert "Completed prompts: 0 | Cache Hit: N/A" in text
    assert "Cache Hit by agent (all models):" not in text
    assert "Cost:" in text


@pytest.mark.parametrize("workflow", [False, True], ids=["session", "workflow"])
def test_agent_rows_distinguish_zero_full_and_unavailable_cache_hits(render, workflow):
    ui, capture = render
    session = _session("main", [
        ("model-a", "zero", {"input": 10, "output": 100}),
        ("model-a", "full", {"cache_read": 10, "output": 100}),
        ("model-b", "empty", {"output": 100}),
        ("model-b", "[red]literal[/red]", {"input": 20, "cache_read": 60, "cache_write": 20}),
    ])
    if workflow:
        group = SessionWorkflow(workflow_id="main", main_session=session)
        panel = ui.create_workflow_model_panel(group, {})
    else:
        panel = ui.create_model_panel(session, {})

    text = capture(panel)

    assert "[red]literal[/red] / model-b" in text
    assert "Completed prompts: N/A | Cache Hit: 60.0%" in text
    assert "Completed prompts: N/A | Cache Hit: N/A" in text
    assert "Completed prompts: N/A | Cache Hit: 100.0%" in text
    assert "Completed prompts: N/A | Cache Hit: 0.0%" in text


@pytest.mark.parametrize("workflow", [False, True], ids=["session", "workflow"])
def test_empty_model_panel_has_no_agent_metrics(render, workflow):
    ui, capture = render
    session = _session("main", [])
    if workflow:
        group = SessionWorkflow(workflow_id="main", main_session=session)
        panel = ui.create_workflow_model_panel(group, {})
    else:
        panel = ui.create_model_panel(session, {})

    text = capture(panel)

    assert "Cache Hit" not in text
    assert "No model data available" in text
    assert "Completed prompts:" not in text


@pytest.mark.parametrize("workflow", [False, True], ids=["session", "workflow"])
@pytest.mark.parametrize("grid", [False, True], ids=["non-grid", "grid"])
@pytest.mark.parametrize("recent", [False, True], ids=["no-recent", "recent"])
def test_dashboard_places_agent_metrics_in_existing_sections_with_tools(render, mixed_workflow, workflow, grid, recent):
    ui, capture = render
    session = mixed_workflow.main_session
    tool = ToolUsageStats(tool_name="read", total_calls=3, success_count=3)
    models = [ModelToolUsage(model_name="model-a", agent_name="build", tool_stats=[tool])]
    if grid:
        models.append(ModelToolUsage(model_name="model-b", agent_name="build", tool_stats=[tool]))
    layout = ui.create_dashboard_layout(
        session, session.files[0] if recent else None, {},
        workflow=mixed_workflow if workflow else None,
        tool_stats_by_model=models,
        completed_turn_counts={"build": 2},
        controls_hint="q: quit",
    )

    text = capture(layout)

    overall = "31.6%" if workflow else "32.3%"
    assert f"Cache Hit: {overall}" in text
    expected = "32.2%" if workflow else "31.7%"
    assert text.count(f"Completed prompts: 2 | Cache Hit: {expected}") == (2 if grid or not workflow else 3)
    assert "Cache Hit by agent (all models):" not in text
    assert "Completed stored prompts by agent:" not in text
    assert "Database-validated stored prompts with completed responses" not in text
    assert "known synthetic excluded" not in text
    assert "read" in text
    assert "Tokens:" in text
    cost = "Total: $1.50" if workflow else "Session: $0.75"
    total = "Total: 2,010" if workflow else "Total: 1,620"
    assert cost in text
    assert total in text
    assert "q: quit" in text


@pytest.mark.parametrize("grid", [False, True], ids=["non-grid", "grid"])
def test_named_agent_sections_keep_their_own_tokens_cost_and_bare_rate_fallback(render, grid):
    ui, capture = render
    session = _session("main", [
        ("provider/shared", "build", {"input": 10, "cache_read": 90}),
        ("provider/shared", "build", {"input": 300, "cache_read": 100, "cache_write": 100}),
        ("provider/shared", None, {"input": 10, "cache_read": 10}),
    ])
    tool = ToolUsageStats(tool_name="read", total_calls=3, success_count=3)
    models = [
        ModelToolUsage(model_name="shared", agent_name="build", tool_stats=[tool]),
        ModelToolUsage(model_name="shared", agent_name=None, tool_stats=[tool]),
    ] if grid else []

    text = capture(ui.create_dashboard_layout(
        session, None, {}, tool_stats_by_model=models,
        completed_turn_counts={"build": 8, "main": 2},
        per_model_output_rates={"shared": 12.5},
        per_model_context={"shared": {"usage_percentage": 25}},
    ))

    assert "Completed prompts: 8 | Cache Hit: 31.7%" in text
    assert "Completed prompts: 2 | Cache Hit: 50.0%" in text
    if grid:
        left, right = [], []
        for line in text.splitlines():
            left.append(line[:110])
            right.append(line[110:])
        build_pane, main_pane = "\n".join(left), "\n".join(right)
        assert "Completed prompts: 8 | Cache Hit: 31.7%" in build_pane
        assert "Completed prompts: 2 | Cache Hit: 50.0%" in main_pane
        assert "Tokens: 600 total" in build_pane
        assert "Tokens: 20 total" in main_pane
        assert "Cost $0.50" in build_pane
        assert "Cost $0.25" in main_pane
        assert "Rate 12.5 tok/s" in build_pane
        assert "Ctx ██░░░░░░ 25%" in build_pane
    else:
        build_row = text.split("build / provider/shared", 1)[1].split("main / provider/shared", 1)[0]
        main_row = text.split("main / provider/shared", 1)[1]
        assert "Completed prompts: 8 | Cache Hit: 31.7%" in build_row
        assert "Completed prompts: 2 | Cache Hit: 50.0%" in main_row
        assert "Tokens: 600 tok" in build_row
        assert "Tokens: 20 tok" in main_row
        assert "Cost: $0.50" in build_row
        assert "Cost: $0.25" in main_row
        assert "12.5 tok/s" in build_row
        assert "context ██░░░░░░ 25%" in build_row


def test_grid_agent_metrics_do_not_use_tool_attributed_tokens(render, mixed_workflow):
    ui, capture = render
    tool = ToolUsageStats(
        tool_name="read", total_calls=1, success_count=1,
        input_tokens=1, cache_read_tokens=999,
    )
    models = [
        ModelToolUsage(model_name="model-a", agent_name="build", tool_stats=[tool]),
        ModelToolUsage(model_name="model-b", agent_name="build"),
    ]

    text = capture(ui.create_dashboard_layout(
        mixed_workflow.main_session, None, {}, workflow=mixed_workflow,
        tool_stats_by_model=models, completed_turn_counts={"build": 17},
    ))

    assert text.count("Completed prompts: 17 | Cache Hit: 32.2%") == 2
    assert "99.9%" not in text
    assert "No tool activity" in text
    assert "read" in text


def test_grid_does_not_invent_panes_for_agents_without_tool_rows(render):
    ui, capture = render
    session = _session("main", [
        ("model-a", f"long-agent-name-{index:02}", {"input": 10, "cache_read": 10})
        for index in range(24)
    ])
    tool = ToolUsageStats(tool_name="read", total_calls=3, success_count=3)
    models = [
        ModelToolUsage(model_name="model-a", tool_stats=[tool]),
        ModelToolUsage(model_name="model-b", tool_stats=[tool]),
    ]

    text = capture(ui.create_dashboard_layout(
        session, None, {}, tool_stats_by_model=models, completed_turn_counts={"build": 2}
    ))

    visible_text = " ".join(text.split())
    assert "long-agent-name" not in visible_text
    assert text.count("Completed prompts: 0 | Cache Hit: N/A") == 2
    assert "Completed stored prompts by agent:" not in text
    assert "read" in text
