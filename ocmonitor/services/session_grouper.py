"""Session grouper for creating workflow groups."""

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Dict

from ..models.session import SessionData
from ..models.workflow import SessionWorkflow
from ..utils.file_utils import SessionMetadata
from .agent_registry import AgentRegistry


@dataclass
class MetadataWorkflow:
    """Lightweight grouped sessions for discovery, without interaction payloads."""

    workflow_id: str
    main_session: SessionMetadata
    sub_agent_sessions: List[SessionMetadata]

    @property
    def project_name(self) -> str:
        return self.main_session.project_name

    @property
    def start_time(self):
        times = [self.main_session.start_time] + [s.start_time for s in self.sub_agent_sessions]
        valid = [time for time in times if time is not None]
        return min(valid) if valid else None

    @property
    def end_time(self):
        times = [self.main_session.end_time] + [s.end_time for s in self.sub_agent_sessions]
        valid = [time for time in times if time is not None]
        return max(valid) if valid else None

    @property
    def display_title(self) -> str:
        return self.main_session.display_title

    @property
    def session_count(self) -> int:
        return 1 + len(self.sub_agent_sessions)

    @property
    def sub_agent_count(self) -> int:
        return len(self.sub_agent_sessions)

    @property
    def all_sessions(self) -> List[SessionMetadata]:
        """Return member metadata in chronological order for ID hydration."""
        return sorted(
            [self.main_session] + self.sub_agent_sessions,
            key=lambda session: session.start_time or datetime.min,
        )

    @property
    def last_activity_ts(self) -> float:
        """Match the picker activity timestamp: only the main session counts."""
        return self.main_session.last_activity_ts


class SessionGrouper:
    """Groups sessions into workflows based on project and agent relationships."""

    def __init__(self, agent_registry: Optional[AgentRegistry] = None):
        """Initialize the session grouper.

        Args:
            agent_registry: AgentRegistry instance for detecting sub-agents.
                           If None, creates a new one.
        """
        self.agent_registry = agent_registry or AgentRegistry()

    def group_sessions(self, sessions: List[SessionData]) -> List[SessionWorkflow]:
        """Group sessions into workflows.

        Each main session becomes a workflow. Sub-agent sessions are linked
        to the most recent main session on the same project that started
        before the sub-agent.

        Args:
            sessions: List of sessions to group

        Returns:
            List of SessionWorkflow objects, sorted by start time (most recent first)
        """
        # Separate main and sub-agent sessions
        sub_agents: List[SessionData] = []
        main_sessions: List[SessionData] = []

        for session in sessions:
            if self._is_sub_agent(session):
                sub_agents.append(session)
            else:
                main_sessions.append(session)

        # Sort main sessions by start time (oldest first for matching)
        main_sessions = sorted(
            main_sessions,
            key=lambda s: s.start_time or datetime.min
        )

        # Sort sub-agents by start time
        sub_agents = sorted(
            sub_agents,
            key=lambda s: s.start_time or datetime.min
        )

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

    def group_session_metadata(self, sessions: List[SessionMetadata]) -> List[MetadataWorkflow]:
        """Group lightweight discovery records using normal project/time rules."""
        sub_agents = [session for session in sessions if self.agent_registry.is_sub_agent(session.agent)]
        main_sessions = [session for session in sessions if not self.agent_registry.is_sub_agent(session.agent)]
        main_sessions.sort(key=lambda session: session.start_time or datetime.min)
        sub_agents.sort(key=lambda session: session.start_time or datetime.min)

        workflows = {
            session.session_id: MetadataWorkflow(session.session_id, session, [])
            for session in main_sessions
        }
        for sub_agent in sub_agents:
            candidates = [
                main for main in main_sessions
                if sub_agent.start_time is not None
                and main.project_name == sub_agent.project_name
                and main.start_time is not None
                and main.start_time <= sub_agent.start_time
            ]
            parent = max(candidates, key=lambda session: session.start_time or datetime.min) if candidates else None
            if parent and parent.session_id in workflows:
                workflows[parent.session_id].sub_agent_sessions.append(sub_agent)
            else:
                workflows[sub_agent.session_id] = MetadataWorkflow(sub_agent.session_id, sub_agent, [])

        return sorted(
            workflows.values(),
            key=lambda workflow: workflow.start_time or datetime.min,
            reverse=True,
        )

    def _is_sub_agent(self, session: SessionData) -> bool:
        """Check if session is a sub-agent session.

        Args:
            session: Session to check

        Returns:
            True if the session is from a sub-agent
        """
        return self.agent_registry.is_sub_agent(session.agent)

    def _find_parent_session(
        self,
        sub_agent: SessionData,
        main_sessions: List[SessionData]
    ) -> Optional[SessionData]:
        """Find the parent main session for a sub-agent.

        Returns the most recent main session on the same project
        that started BEFORE the sub-agent.

        Args:
            sub_agent: Sub-agent session to find parent for
            main_sessions: List of main sessions to search

        Returns:
            Parent SessionData or None if no match found
        """
        if sub_agent.start_time is None:
            return None

        candidates: List[SessionData] = []
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
        return max(candidates, key=lambda s: s.start_time or datetime.min)

    def reload_agents(self):
        """Reload agent definitions."""
        self.agent_registry.reload()
