# Implementation Plan: Workflow Session Grouping

## Overview
Group related sessions (main session + sub-agent sessions) into "Workflow Groups" based on project path. This addresses the issue where sub-agent sessions create separate session folders that should be viewed together with their parent session.

## Key Insight
- **Sub-agents**: Create separate session directories, identified by `mode: subagent` in ~/.config/opencode/agent/*.md files
- **Main agents**: Stay in the same session, identified by `mode: primary` (or no mode) in agent definitions
- **Dynamic Discovery**: System automatically detects any custom sub-agents users create

## Built-in Agent Types
- **Main agents**: `plan`, `build`
- **Sub-agents**: `explore`

User-defined agents are detected automatically from `~/.config/opencode/agent/*.md` files.

## Grouping Logic (Simplified)

**No time window needed.** Sub-agents are linked to the most recent main session on the same project:

```
For each sub-agent session:
  1. Filter main sessions by same project_name
  2. Filter main sessions that started BEFORE the sub-agent
  3. Pick the most recent one (closest in time)
  4. Link sub-agent to that main session
```

---

## Implementation Details

### 1. Create AgentRegistry Service
**File**: `ocmonitor/ocmonitor/services/agent_registry.py`

```python
from pathlib import Path
from typing import Dict, Any, Set, Optional

class AgentRegistry:
    """Discovers and manages agent definitions from OpenCode config."""

    # Built-in agents (fallback if no config directory exists)
    BUILTIN_MAIN_AGENTS = {'plan', 'build'}
    BUILTIN_SUB_AGENTS = {'explore'}

    def __init__(self, agents_dir: Optional[Path] = None):
        self.agents_dir = agents_dir or Path.home() / ".config" / "opencode" / "agent"
        self._sub_agents: Set[str] = set()
        self._main_agents: Set[str] = set()
        self._load_agents()

    def _load_agents(self):
        """Scan ~/.config/opencode/agent/ for agent definitions."""
        # Start with built-in agents
        self._main_agents = self.BUILTIN_MAIN_AGENTS.copy()
        self._sub_agents = self.BUILTIN_SUB_AGENTS.copy()

        if not self.agents_dir.exists():
            return

        for md_file in self.agents_dir.glob("*.md"):
            agent_name = md_file.stem  # filename without .md
            agent_config = self._parse_agent_file(md_file)

            mode = agent_config.get('mode', '').lower()
            if mode == 'subagent':
                self._sub_agents.add(agent_name)
            elif mode == 'primary':
                self._main_agents.add(agent_name)
            # If no mode specified, agent is treated as main (default behavior)

    def _parse_agent_file(self, file_path: Path) -> Dict[str, Any]:
        """Parse YAML frontmatter from markdown agent file."""
        try:
            content = file_path.read_text()

            # Extract YAML frontmatter between --- markers
            if content.startswith('---'):
                parts = content.split('---', 2)
                if len(parts) >= 3:
                    import yaml
                    return yaml.safe_load(parts[1]) or {}
        except Exception:
            pass
        return {}

    def is_sub_agent(self, agent_name: str) -> bool:
        """Check if an agent is a sub-agent."""
        if agent_name is None:
            return False
        return agent_name.lower() in self._sub_agents

    def is_main_agent(self, agent_name: str) -> bool:
        """Check if an agent is a main agent."""
        if agent_name is None:
            return True  # Default to main if unknown
        return agent_name.lower() in self._main_agents or agent_name.lower() not in self._sub_agents

    def get_all_sub_agents(self) -> Set[str]:
        """Get all registered sub-agent names."""
        return self._sub_agents.copy()

    def get_all_main_agents(self) -> Set[str]:
        """Get all registered main agent names."""
        return self._main_agents.copy()

    def reload(self):
        """Reload agent definitions (for when user adds new agents)."""
        self._sub_agents.clear()
        self._main_agents.clear()
        self._load_agents()
```

### 2. Update InteractionFile Model
**File**: `ocmonitor/ocmonitor/models/session.py`

Add `agent` field to capture the agent type from JSON:
```python
class InteractionFile(BaseModel):
    # ... existing fields ...
    agent: Optional[str] = Field(default=None, description="Agent type (explore, plan, etc.)")
```

### 3. Update SessionData Model
**File**: `ocmonitor/ocmonitor/models/session.py`

Add `agent` field at session level (extracted from first interaction):
```python
class SessionData(BaseModel):
    # ... existing fields ...
    agent: Optional[str] = Field(default=None, description="Agent type for this session")
```

### 4. Update File Parser
**File**: `ocmonitor/ocmonitor/utils/file_utils.py`

In `parse_interaction_file()`, extract the agent field:
```python
agent = data.get('agent')
```

When creating SessionData, set agent from first interaction file.

### 5. Create SessionWorkflow Model
**File**: `ocmonitor/ocmonitor/models/workflow.py` (new file)

```python
from pydantic import BaseModel, computed_field
from typing import List, Optional
from datetime import datetime
from decimal import Decimal
from .session import SessionData, TokenUsage

class SessionWorkflow(BaseModel):
    """Represents a group of related sessions (main + sub-agents)."""
    workflow_id: str  # Same as main session ID
    main_session: SessionData
    sub_agent_sessions: List[SessionData] = []

    @computed_field
    @property
    def project_name(self) -> str:
        return self.main_session.project_name

    @computed_field
    @property
    def start_time(self) -> Optional[datetime]:
        times = [self.main_session.start_time] + [s.start_time for s in self.sub_agent_sessions]
        valid_times = [t for t in times if t is not None]
        return min(valid_times) if valid_times else None

    @computed_field
    @property
    def end_time(self) -> Optional[datetime]:
        times = [self.main_session.end_time] + [s.end_time for s in self.sub_agent_sessions]
        valid_times = [t for t in times if t is not None]
        return max(valid_times) if valid_times else None

    @computed_field
    @property
    def total_tokens(self) -> TokenUsage:
        """Aggregate tokens across main + all sub-agents."""
        all_sessions = [self.main_session] + self.sub_agent_sessions
        return TokenUsage(
            input=sum(s.tokens.input for s in all_sessions),
            output=sum(s.tokens.output for s in all_sessions),
            cache_read=sum(s.tokens.cache_read for s in all_sessions),
            cache_write=sum(s.tokens.cache_write for s in all_sessions),
        )

    @computed_field
    @property
    def total_cost(self) -> Decimal:
        """Aggregate cost across all sessions."""
        all_sessions = [self.main_session] + self.sub_agent_sessions
        return sum(s.cost for s in all_sessions)

    @computed_field
    @property
    def session_count(self) -> int:
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
```

### 6. Create SessionGrouper Service
**File**: `ocmonitor/ocmonitor/services/session_grouper.py`

```python
from typing import List, Optional
from ..models.session import SessionData
from ..models.workflow import SessionWorkflow
from .agent_registry import AgentRegistry

class SessionGrouper:
    """Groups sessions into workflows based on project."""

    def __init__(self, agent_registry: Optional[AgentRegistry] = None):
        self.agent_registry = agent_registry or AgentRegistry()

    def group_sessions(self, sessions: List[SessionData]) -> List[SessionWorkflow]:
        """Group sessions into workflows."""
        # Separate main and sub-agent sessions
        sub_agents = []
        main_sessions = []

        for session in sessions:
            if self._is_sub_agent(session):
                sub_agents.append(session)
            else:
                main_sessions.append(session)

        # Sort main sessions by start time (oldest first)
        main_sessions = sorted(main_sessions, key=lambda s: s.start_time or datetime.min)

        # Sort sub-agents by start time
        sub_agents = sorted(sub_agents, key=lambda s: s.start_time or datetime.min)

        # Build workflows - each main session becomes a workflow
        workflows: Dict[str, SessionWorkflow] = {}
        for main in main_sessions:
            workflows[main.session_id] = SessionWorkflow(
                workflow_id=main.session_id,
                main_session=main,
                sub_agent_sessions=[]
            )

        # Link each sub-agent to the most recent main session on same project
        for sub in sub_agents:
            parent = self._find_parent_session(sub, main_sessions)
            if parent and parent.session_id in workflows:
                workflows[parent.session_id].sub_agent_sessions.append(sub)
            else:
                # Orphan sub-agent - create standalone workflow
                workflows[sub.session_id] = SessionWorkflow(
                    workflow_id=sub.session_id,
                    main_session=sub,  # Treat as main for display
                    sub_agent_sessions=[]
                )

        # Return workflows sorted by start time (most recent first)
        return sorted(
            workflows.values(),
            key=lambda w: w.start_time or datetime.min,
            reverse=True
        )

    def _is_sub_agent(self, session: SessionData) -> bool:
        """Check if session is a sub-agent session."""
        return self.agent_registry.is_sub_agent(session.agent)

    def _find_parent_session(
        self,
        sub_agent: SessionData,
        main_sessions: List[SessionData]
    ) -> Optional[SessionData]:
        """Find the parent main session for a sub-agent.

        Returns the most recent main session on the same project
        that started BEFORE the sub-agent.
        """
        if sub_agent.start_time is None:
            return None

        candidates = []
        for main in main_sessions:
            # Must be same project
            if main.project_name != sub_agent.project_name:
                continue

            # Main must have started before sub-agent
            if main.start_time is None:
                continue
            if main.start_time > sub_agent.start_time:
                continue

            candidates.append(main)

        if not candidates:
            return None

        # Return the most recent candidate (closest in time to sub-agent)
        return max(candidates, key=lambda s: s.start_time)

    def reload_agents(self):
        """Reload agent definitions."""
        self.agent_registry.reload()
```

### 7. Update Sessions Report
**File**: `ocmonitor/ocmonitor/services/report_generator.py`

Add method to generate workflow-grouped report:
```python
def generate_sessions_report(self, sessions: List[SessionData], group_workflows: bool = True):
    if group_workflows:
        grouper = SessionGrouper()
        workflows = grouper.group_sessions(sessions)
        self._display_workflow_table(workflows)
    else:
        # Original ungrouped display
        self._display_sessions_table(sessions)

def _display_workflow_table(self, workflows: List[SessionWorkflow]):
    """Display sessions grouped by workflow."""
    table = Table(title="Session Workflows")
    table.add_column("Workflow", style="cyan")
    table.add_column("Sessions", justify="right")
    table.add_column("Cost", justify="right")
    table.add_column("Tokens", justify="right")
    table.add_column("Project")

    for workflow in workflows:
        # Add workflow summary row
        table.add_row(
            workflow.session_title[:40] + "..." if len(workflow.session_title) > 40 else workflow.session_title,
            str(workflow.session_count),
            f"${workflow.total_cost:.2f}",
            format_tokens(workflow.total_tokens.total),
            workflow.project_name,
            style="bold"
        )

        # Add sub-rows for each session in workflow
        if workflow.session_count > 1:
            # Main session
            table.add_row(
                f"  └─ Main ({workflow.main_session.agent or 'unknown'})",
                "",
                f"${workflow.main_session.cost:.2f}",
                format_tokens(workflow.main_session.tokens.total),
                "",
                style="dim"
            )
            # Sub-agent sessions
            for i, sub in enumerate(workflow.sub_agent_sessions):
                prefix = "  └─" if i == len(workflow.sub_agent_sessions) - 1 else "  ├─"
                table.add_row(
                    f"{prefix} Sub ({sub.agent or 'unknown'})",
                    "",
                    f"${sub.cost:.2f}",
                    format_tokens(sub.tokens.total),
                    "",
                    style="dim"
                )

    console.print(table)
```

### 8. Update Live Monitor
**File**: `ocmonitor/ocmonitor/services/live_monitor.py`

Modify to monitor entire workflow:
```python
def start_monitoring(self, base_path: str, refresh_interval: int = 5):
    # Load recent sessions
    all_sessions = FileProcessor.load_all_sessions(base_path, limit=50)

    # Group into workflows
    grouper = SessionGrouper()
    workflows = grouper.group_sessions(all_sessions)

    if not workflows:
        console.print("[yellow]No sessions found[/yellow]")
        return

    # Get most recent workflow
    current_workflow = workflows[0]

    with Live(refresh_per_second=1) as live:
        while True:
            # Reload all sessions in the workflow
            updated_sessions = []
            for session in current_workflow.all_sessions:
                updated = FileProcessor.load_session_data(session.session_path)
                if updated:
                    updated_sessions.append(updated)

            # Rebuild workflow with updated data
            current_workflow = SessionWorkflow(
                workflow_id=current_workflow.workflow_id,
                main_session=updated_sessions[0] if updated_sessions else current_workflow.main_session,
                sub_agent_sessions=updated_sessions[1:] if len(updated_sessions) > 1 else []
            )

            live.update(self._generate_workflow_dashboard(current_workflow))
            time.sleep(refresh_interval)
```

### 9. Configuration
**File**: `ocmonitor/config.toml`

Add workflow settings:
```toml
[workflow]
enabled = true  # Enable workflow grouping by default
agents_config_dir = "~/.config/opencode/agent"  # Where to find agent definitions
```

### 10. CLI Commands
**File**: `ocmonitor/ocmonitor/cli.py`

Add `--no-group` flag to sessions command:
```python
@cli.command()
@click.option('--no-group', is_flag=True, help='Show sessions without workflow grouping')
def sessions(path, limit, no_group):
    """List all sessions."""
    sessions = load_sessions(path, limit)
    report_generator.generate_sessions_report(sessions, group_workflows=not no_group)
```

Add agents command:
```python
@cli.command()
def agents():
    """List all detected agents and their types."""
    registry = AgentRegistry()

    console.print("[bold]Main agents (stay in same session):[/bold]")
    for agent in sorted(registry.get_all_main_agents()):
        console.print(f"  - {agent}")

    console.print("\n[bold]Sub-agents (create separate sessions):[/bold]")
    for agent in sorted(registry.get_all_sub_agents()):
        console.print(f"  - {agent}")
```

### 11. Update Dependencies
**File**: `ocmonitor/requirements.txt`

Add PyYAML:
```
PyYAML>=6.0
```

---

## Edge Cases

1. **Multiple sub-agents for same main session**
   - All get linked to the same workflow (correct behavior)

2. **Sub-agent session without matching main session (orphan)**
   - Display as standalone workflow

3. **Agent config directory doesn't exist**
   - Fall back to built-in agent lists

4. **Invalid YAML in agent markdown file**
   - Log warning, skip file, continue with other agents

5. **Session missing `agent` field**
   - Default to main agent behavior

6. **Multiple main sessions on same project**
   - Each becomes its own workflow; sub-agents link to most recent preceding main

---

## Testing Strategy

1. **Unit Tests**:
   - AgentRegistry: parse YAML, handle missing files, fallback to built-ins
   - SessionGrouper: correct grouping, orphan handling, sorting

2. **Mock Data**:
   - Main session + 2 sub-agents (verify grouping)
   - Two separate workflows on same project (verify they don't merge)
   - Orphan sub-agent (verify standalone workflow created)

3. **Integration Tests**:
   - Test with actual ~/.config/opencode/agent/ directory
   - Verify custom sub-agents are detected and grouped correctly

---

## Implementation Order

1. Add `agent` field to InteractionFile and SessionData models
2. Update file parser to extract `agent` field
3. Create AgentRegistry service
4. Create SessionWorkflow model
5. Create SessionGrouper service
6. Update sessions report to use workflow grouping
7. Update live monitor to track entire workflow
8. Add CLI flags and agents command
9. Add tests
