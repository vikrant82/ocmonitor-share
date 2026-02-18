"""SQLite database utilities for OpenCode v1.2.0+ session storage."""

import json
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Any, Generator
from datetime import datetime

from ..models.session import SessionData, InteractionFile, TokenUsage, TimeData


class SQLiteProcessor:
    """Handles SQLite database queries for OpenCode v1.2.0+ session storage."""

    DEFAULT_DB_PATH = Path.home() / ".local" / "share" / "opencode" / "opencode.db"

    @staticmethod
    def find_database_path(custom_path: Optional[Path] = None) -> Optional[Path]:
        """Find the OpenCode SQLite database.

        Args:
            custom_path: Optional custom path to check first

        Returns:
            Path to database file if found, None otherwise
        """
        if custom_path and custom_path.exists():
            return custom_path

        if SQLiteProcessor.DEFAULT_DB_PATH.exists():
            return SQLiteProcessor.DEFAULT_DB_PATH

        # Check Windows location
        import os

        if os.name == "nt":
            windows_path = (
                Path(os.environ.get("APPDATA", "")) / "opencode" / "opencode.db"
            )
            if windows_path.exists():
                return windows_path

        return None

    @staticmethod
    def _get_connection(db_path: Path) -> sqlite3.Connection:
        """Create a database connection with proper settings."""
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _extract_model_name(model_data: Any) -> str:
        """Extract model name from various possible locations in message data."""
        if isinstance(model_data, dict):
            # Try modelID directly
            if "modelID" in model_data:
                return model_data["modelID"]
            # Try nested model.modelID
            if "model" in model_data and isinstance(model_data["model"], dict):
                return model_data["model"].get("modelID", "unknown")
        return "unknown"

    @staticmethod
    def _extract_tokens(message_json: Dict[str, Any]) -> TokenUsage:
        """Extract token usage from message JSON data."""
        tokens_data = message_json.get("tokens", {})
        cache_data = tokens_data.get("cache", {})

        return TokenUsage(
            input=tokens_data.get("input", 0),
            output=tokens_data.get("output", 0),
            cache_write=cache_data.get("write", 0),
            cache_read=cache_data.get("read", 0),
        )

    @staticmethod
    def _extract_time_data(message_json: Dict[str, Any]) -> Optional[TimeData]:
        """Extract timing information from message JSON data."""
        time_data = message_json.get("time", {})
        if time_data:
            return TimeData(
                created=time_data.get("created"), completed=time_data.get("completed")
            )
        return None

    @staticmethod
    def _extract_project_path(message_json: Dict[str, Any]) -> Optional[str]:
        """Extract project path from message JSON data."""
        path_data = message_json.get("path", {})
        if path_data:
            # Prefer cwd, fallback to root
            return path_data.get("cwd") or path_data.get("root")
        return None

    @staticmethod
    def _extract_agent(message_json: Dict[str, Any]) -> Optional[str]:
        """Extract agent type from message JSON data."""
        return message_json.get("agent")

    @classmethod
    def parse_message_data(
        cls, message_data_str: str, session_id: str
    ) -> Optional[InteractionFile]:
        """Parse a message data JSON string into an InteractionFile.

        Args:
            message_data_str: JSON string from message.data column
            session_id: ID of the session this message belongs to

        Returns:
            InteractionFile object or None if parsing failed
        """
        try:
            data = json.loads(message_data_str)
        except (json.JSONDecodeError, TypeError):
            return None

        if not isinstance(data, dict):
            return None

        # Only process assistant messages with tokens
        role = data.get("role", "")
        if role != "assistant":
            return None

        tokens = cls._extract_tokens(data)

        # Filter out interactions with zero token usage
        if tokens.total == 0:
            return None

        time_data = cls._extract_time_data(data)
        project_path = cls._extract_project_path(data)
        agent = cls._extract_agent(data)
        model_id = cls._extract_model_name(data)

        return InteractionFile(
            file_path=Path("sqlite") / session_id,  # Placeholder path
            session_id=session_id,
            model_id=model_id,
            tokens=tokens,
            time_data=time_data,
            project_path=project_path,
            agent=agent,
            raw_data=data,
        )

    @classmethod
    def load_session_messages(
        cls, conn: sqlite3.Connection, session_id: str
    ) -> List[InteractionFile]:
        """Load all messages for a session.

        Args:
            conn: Database connection
            session_id: Session ID to load messages for

        Returns:
            List of InteractionFile objects
        """
        cursor = conn.execute(
            "SELECT data FROM message WHERE session_id = ? ORDER BY time_created",
            (session_id,),
        )

        interactions = []
        for row in cursor:
            interaction = cls.parse_message_data(row["data"], session_id)
            if interaction:
                interactions.append(interaction)

        return interactions

    @classmethod
    def load_session_data(
        cls, conn: sqlite3.Connection, session_row: sqlite3.Row
    ) -> Optional[SessionData]:
        """Load complete session data from a database row.

        Args:
            conn: Database connection
            session_row: Row from session table

        Returns:
            SessionData object or None if loading failed
        """
        session_id = session_row["id"]

        # Load all messages/interactions for this session
        interaction_files = cls.load_session_messages(conn, session_id)

        if not interaction_files:
            return None

        # Get agent from first interaction
        sorted_files = sorted(
            interaction_files,
            key=lambda f: (
                f.time_data.created if f.time_data and f.time_data.created else 0
            ),
        )
        session_agent = sorted_files[0].agent if sorted_files else None

        # Determine if this is a sub-agent
        parent_id = session_row["parent_id"]
        is_sub_agent = parent_id is not None

        return SessionData(
            session_id=session_id,
            session_path=None,  # SQLite sessions don't have file paths
            parent_id=parent_id,
            is_sub_agent=is_sub_agent,
            files=interaction_files,
            session_title=session_row["title"],
            agent=session_agent,
            source="sqlite",
        )

    @classmethod
    def load_all_sessions(
        cls, db_path: Optional[Path] = None, limit: Optional[int] = None
    ) -> List[SessionData]:
        """Load all sessions from the SQLite database.

        Args:
            db_path: Path to database (uses default if not provided)
            limit: Maximum number of sessions to load (None for all)

        Returns:
            List of SessionData objects sorted by creation time (newest first)
        """
        if db_path is None:
            db_path = cls.find_database_path()

        if not db_path or not db_path.exists():
            return []

        conn = cls._get_connection(db_path)
        try:
            # Query all sessions with project info
            query = """
                SELECT s.*, p.worktree as project_path, p.name as project_name
                FROM session s
                LEFT JOIN project p ON s.project_id = p.id
                ORDER BY s.time_created DESC
            """

            if limit:
                query += f" LIMIT {limit}"

            cursor = conn.execute(query)
            sessions = []

            for row in cursor:
                session_data = cls.load_session_data(conn, row)
                if session_data:
                    sessions.append(session_data)

            return sessions
        finally:
            conn.close()

    @classmethod
    def load_session_hierarchy(cls, db_path: Optional[Path] = None) -> Dict[str, Any]:
        """Load sessions organized by parent-child hierarchy.

        Args:
            db_path: Path to database (uses default if not provided)

        Returns:
            Dictionary with:
                - 'root_sessions': List of parent sessions with sub_agents
                - 'all_sessions': Flat list of all sessions
                - 'source': 'sqlite'
        """
        all_sessions = cls.load_all_sessions(db_path)

        # Organize by parent_id
        parent_map: Dict[str, List[SessionData]] = {}
        root_sessions: List[Dict[str, Any]] = []
        session_lookup: Dict[str, SessionData] = {}

        for session in all_sessions:
            session_lookup[session.session_id] = session

        # Group sub-agents by parent
        for session in all_sessions:
            if session.parent_id:
                if session.parent_id not in parent_map:
                    parent_map[session.parent_id] = []
                parent_map[session.parent_id].append(session)

        # Build hierarchy
        for session in all_sessions:
            if not session.parent_id:  # Root session
                sub_agents = parent_map.get(session.session_id, [])
                # Sort sub-agents by creation time
                sub_agents.sort(key=lambda s: s.start_time or datetime.min)

                root_sessions.append({"session": session, "sub_agents": sub_agents})

        # Sort root sessions by creation time (newest first)
        root_sessions.sort(
            key=lambda x: x["session"].start_time or datetime.min, reverse=True
        )

        return {
            "root_sessions": root_sessions,
            "all_sessions": all_sessions,
            "source": "sqlite",
        }

    @classmethod
    def session_generator(
        cls, db_path: Optional[Path] = None
    ) -> Generator[SessionData, None, None]:
        """Generator that yields sessions one by one (memory efficient).

        Args:
            db_path: Path to database (uses default if not provided)

        Yields:
            SessionData objects
        """
        if db_path is None:
            db_path = cls.find_database_path()

        if not db_path or not db_path.exists():
            return

        conn = cls._get_connection(db_path)
        try:
            cursor = conn.execute("""
                SELECT s.*, p.worktree as project_path, p.name as project_name
                FROM session s
                LEFT JOIN project p ON s.project_id = p.id
                ORDER BY s.time_created DESC
            """)

            for row in cursor:
                session_data = cls.load_session_data(conn, row)
                if session_data:
                    yield session_data
        finally:
            conn.close()

    @classmethod
    def get_most_recent_workflow(
        cls, db_path: Optional[Path] = None
    ) -> Optional[Dict[str, Any]]:
        """Get the most recent workflow (parent session + sub-agents).

        Finds the most recent parent session that has actual message data
        (interactions), skipping empty sessions like ACP sessions.

        Args:
            db_path: Path to database (uses default if not provided)

        Returns:
            Dictionary with workflow data compatible with SessionWorkflow:
                - 'main_session': SessionData (parent session)
                - 'sub_agents': List[SessionData] (sorted by creation time)
                - 'all_sessions': List[SessionData] (main + sub-agents)
                - 'project_name': str
                - 'display_title': str
                - 'session_count': int (total sessions in workflow)
                - 'sub_agent_count': int (number of sub-agents)
                - 'has_sub_agents': bool
                - 'workflow_id': str (main session ID)

        Returns None if no sessions with data found.
        """
        if db_path is None:
            db_path = cls.find_database_path()

        if not db_path or not db_path.exists():
            return None

        conn = cls._get_connection(db_path)
        try:
            # Get recent parent sessions (no parent_id) and check which have messages
            # We check up to 10 recent parents to find one with actual data
            parent_rows = conn.execute("""
                SELECT s.*, p.worktree as project_path, p.name as project_name
                FROM session s
                LEFT JOIN project p ON s.project_id = p.id
                WHERE s.parent_id IS NULL
                ORDER BY s.time_created DESC
                LIMIT 10
            """).fetchall()

            if not parent_rows:
                return None

            # Try each parent until we find one with data
            main_session = None
            for parent_row in parent_rows:
                session = cls.load_session_data(conn, parent_row)
                if session and session.files:  # Has interactions
                    main_session = session
                    break

            if not main_session:
                return None

            return cls._build_workflow_dict(conn, main_session)
        finally:
            conn.close()

    @classmethod
    def _build_workflow_dict(
        cls, conn: sqlite3.Connection, main_session: SessionData
    ) -> Dict[str, Any]:
        sub_agent_rows = conn.execute(
            """
            SELECT s.*, p.worktree as project_path, p.name as project_name
            FROM session s
            LEFT JOIN project p ON s.project_id = p.id
            WHERE s.parent_id = ?
            ORDER BY s.time_created ASC
        """,
            (main_session.session_id,),
        ).fetchall()

        sub_agents = []
        for row in sub_agent_rows:
            sub_session = cls.load_session_data(conn, row)
            if sub_session:
                sub_agents.append(sub_session)

        all_sessions = [main_session] + sub_agents

        return {
            "main_session": main_session,
            "sub_agents": sub_agents,
            "all_sessions": all_sessions,
            "project_name": main_session.project_name,
            "display_title": main_session.display_title,
            "session_count": len(all_sessions),
            "sub_agent_count": len(sub_agents),
            "has_sub_agents": len(sub_agents) > 0,
            "workflow_id": main_session.session_id,
        }

    @classmethod
    def get_all_active_workflows(
        cls, db_path: Optional[Path] = None, active_threshold_minutes: int = 30
    ) -> List[Dict[str, Any]]:
        """Get all active workflows (parent sessions that are still ongoing).

        A workflow is considered active if its most recent message is within
        active_threshold_minutes (default 30). This avoids relying on time_archived
        which may not be set reliably when sessions end.

        Args:
            db_path: Path to database (uses default if not provided)
            active_threshold_minutes: Consider session active if activity within this window

        Returns:
            List of workflow dictionaries, sorted by most recent activity first.
            Each dict has the same structure as get_most_recent_workflow().
        """
        if db_path is None:
            db_path = cls.find_database_path()

        if not db_path or not db_path.exists():
            return []

        conn = cls._get_connection(db_path)
        try:
            import time

            threshold_ms = int(time.time() * 1000) - (
                active_threshold_minutes * 60 * 1000
            )

            parent_rows = conn.execute(
                """
                SELECT s.*, p.worktree as project_path, p.name as project_name
                FROM session s
                LEFT JOIN project p ON s.project_id = p.id
                WHERE s.parent_id IS NULL
                AND EXISTS (
                    SELECT 1 FROM message m
                    WHERE m.session_id = s.id AND m.time_created > ?
                )
                ORDER BY s.time_created DESC
                LIMIT 10
            """,
                (threshold_ms,),
            ).fetchall()

            if not parent_rows:
                return []

            active_workflows = []
            for parent_row in parent_rows:
                session = cls.load_session_data(conn, parent_row)
                if session and session.files:
                    active_workflows.append(cls._build_workflow_dict(conn, session))

            return active_workflows
        finally:
            conn.close()

    @classmethod
    def get_database_stats(cls, db_path: Optional[Path] = None) -> Dict[str, Any]:
        """Get statistics about the SQLite database.

        Args:
            db_path: Path to database (uses default if not provided)

        Returns:
            Dictionary with database statistics
        """
        if db_path is None:
            db_path = cls.find_database_path()

        if not db_path or not db_path.exists():
            return {"exists": False}

        conn = cls._get_connection(db_path)
        try:
            stats = {"exists": True, "path": str(db_path)}

            # Get counts
            stats["session_count"] = conn.execute(
                "SELECT COUNT(*) FROM session"
            ).fetchone()[0]

            stats["message_count"] = conn.execute(
                "SELECT COUNT(*) FROM message"
            ).fetchone()[0]

            stats["project_count"] = conn.execute(
                "SELECT COUNT(*) FROM project"
            ).fetchone()[0]

            # Get sub-agent count
            stats["sub_agent_count"] = conn.execute(
                "SELECT COUNT(*) FROM session WHERE parent_id IS NOT NULL"
            ).fetchone()[0]

            # Get file size
            stats["file_size_bytes"] = db_path.stat().st_size

            return stats
        finally:
            conn.close()
