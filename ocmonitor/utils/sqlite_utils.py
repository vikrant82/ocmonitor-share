"""SQLite database utilities for OpenCode v1.2.0+ session storage."""

import json
import sqlite3
import statistics
import time
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Any, Generator, Sequence
from datetime import datetime

from ..utils.file_utils import FileProcessor
from ..models.session import SessionData, InteractionFile, TokenUsage, TimeData
from ..models.tool_usage import ToolUsageStats, ToolUsageSummary, ModelToolUsage
from ..models.analytics import ModelDetailStats


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
        import os

        candidates: List[Path] = []

        # 1) Explicit custom path (highest priority)
        if custom_path:
            candidates.append(Path(custom_path))

        # 2) Environment override
        env_db_path = os.environ.get("OCMONITOR_DATABASE_FILE")
        if env_db_path:
            candidates.append(Path(os.path.expanduser(os.path.expandvars(env_db_path))))

        # 3) Config path (if available)
        try:
            from ..config import config_manager

            configured_db_path = config_manager.config.paths.database_file
            if configured_db_path:
                candidates.append(
                    Path(os.path.expanduser(os.path.expandvars(configured_db_path)))
                )
        except Exception:
            # Config is optional for path discovery; continue with defaults
            pass

        # 4) Built-in platform defaults
        candidates.append(SQLiteProcessor.DEFAULT_DB_PATH)

        if os.name == "nt":
            candidates.append(
                Path(os.environ.get("APPDATA", "")) / "opencode" / "opencode.db"
            )

        for candidate in candidates:
            if candidate.exists():
                return candidate

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
                return model_data["modelID"] or "unknown"
            # Try nested model.modelID
            if "model" in model_data and isinstance(model_data["model"], dict):
                return model_data["model"].get("modelID") or "unknown"
        return "unknown"

    @staticmethod
    def _extract_tokens(message_json: Dict[str, Any]) -> TokenUsage:
        """Extract token usage from message JSON data."""
        tokens_data = message_json.get("tokens", {})
        cache_data = tokens_data.get("cache", {})

        return TokenUsage(
            input=max(0, tokens_data.get("input", 0)),
            output=max(0, tokens_data.get("output", 0)),
            cache_write=max(0, cache_data.get("write", 0)),
            cache_read=max(0, cache_data.get("read", 0)),
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
        cls,
        message_data_str: str,
        session_id: str,
        message_id: Optional[str] = None,
        time_created: Optional[int] = None,
        time_updated: Optional[int] = None,
    ) -> Optional[InteractionFile]:
        """Parse a message data JSON string into an InteractionFile.

        Args:
            message_data_str: JSON string from message.data column
            session_id: ID of the session this message belongs to
            message_id: Optional SQLite message ID for related part lookup
            time_created: Optional SQLite message creation timestamp
            time_updated: Optional SQLite message update timestamp

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
        time_data = cls._extract_time_data(data)
        project_path = cls._extract_project_path(data)
        agent = cls._extract_agent(data)
        model_id = cls._extract_model_name(data).lower()
        provider_id = (data.get("providerID") or "").lower() or None
        finish_reason = data.get("finish")
        raw_data = dict(data)
        if message_id is not None:
            raw_data["_message_id"] = message_id
        if time_created is not None:
            raw_data["_message_time_created"] = time_created
        if time_updated is not None:
            raw_data["_message_time_updated"] = time_updated

        return InteractionFile(
            file_path=Path("sqlite") / session_id,  # Placeholder path
            session_id=session_id,
            model_id=model_id,
            provider_id=provider_id,
            tokens=tokens,
            time_data=time_data,
            project_path=project_path,
            agent=agent,
            finish_reason=finish_reason,
            raw_data=raw_data,
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
            "SELECT id, time_created, time_updated, data FROM message WHERE session_id = ? ORDER BY time_created",
            (session_id,),
        )

        interactions = []
        for row in cursor:
            interaction = cls.parse_message_data(
                row["data"],
                session_id,
                message_id=row["id"],
                time_created=row["time_created"],
                time_updated=row["time_updated"],
            )
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

        # Filter out zero-token interactions (consistent with FileProcessor)
        interaction_files = [f for f in interaction_files if f.tokens.total > 0]

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
    def get_recent_workflows(
        cls, db_path: Optional[Path] = None, limit: int = 5
    ) -> List[Dict[str, Any]]:
        """Get the most recent workflows (parent session + sub-agents).

        Finds parent sessions that have actual message data (interactions),
        skipping empty sessions, up to the specified limit.

        Args:
            db_path: Path to database (uses default if not provided)
            limit: Maximum number of workflows to return

        Returns:
            List of dictionaries with workflow data compatible with SessionWorkflow.
        """
        if db_path is None:
            db_path = cls.find_database_path()

        if not db_path or not db_path.exists():
            return []

        conn = cls._get_connection(db_path)
        try:
            # Get recent parent sessions (no parent_id)
            parent_rows = conn.execute(
                """
                SELECT s.*, p.worktree as project_path, p.name as project_name
                FROM session s
                LEFT JOIN project p ON s.project_id = p.id
                WHERE s.parent_id IS NULL
                ORDER BY s.time_created DESC
                LIMIT ?
            """,
                (limit * 5,),
            ).fetchall()

            if not parent_rows:
                return []

            workflows = []
            for parent_row in parent_rows:
                session = cls.load_session_data(conn, parent_row)
                if session and session.files:  # Has interactions
                    workflows.append(cls._build_workflow_dict(conn, session))
                    if len(workflows) >= limit:
                        break

            return workflows
        finally:
            conn.close()

    @classmethod
    def get_workflow_by_id(
        cls, workflow_id: str, db_path: Optional[Path] = None
    ) -> Optional[Dict[str, Any]]:
        """Get a specific workflow by its ID (main session or sub-agent ID)."""
        if db_path is None:
            db_path = cls.find_database_path()

        if not db_path or not db_path.exists():
            return None

        conn = cls._get_connection(db_path)
        try:
            # First, check if the session exists and get its parent_id
            row = conn.execute(
                """
                SELECT s.*, p.worktree as project_path, p.name as project_name
                FROM session s
                LEFT JOIN project p ON s.project_id = p.id
                WHERE s.id = ?
            """,
                (workflow_id,),
            ).fetchone()

            if not row:
                return None

            parent_id = row["parent_id"]
            if parent_id:
                # It's a sub-agent, load the parent session instead
                parent_row = conn.execute(
                    """
                    SELECT s.*, p.worktree as project_path, p.name as project_name
                    FROM session s
                    LEFT JOIN project p ON s.project_id = p.id
                    WHERE s.id = ?
                """,
                    (parent_id,),
                ).fetchone()
                if parent_row:
                    main_session = cls.load_session_data(conn, parent_row)
                else:
                    # Parent not found (orphan), treat the sub-agent as its own main
                    main_session = cls.load_session_data(conn, row)
            else:
                main_session = cls.load_session_data(conn, row)

            if not main_session:
                return None

            return cls._build_workflow_dict(conn, main_session)
        finally:
            conn.close()

    @classmethod
    def _metadata_session_rows(
        cls, conn: sqlite3.Connection, session_ids: List[str]
    ) -> List[sqlite3.Row]:
        """Return eligible metadata only for the supplied candidate session IDs.

        Callers first bound roots by recency/activity, then add only their direct
        children. JSON is inspected inside SQLite; message data is never returned.
        """
        if not session_ids:
            return []
        placeholders = ",".join("?" for _ in session_ids)
        query = f"""
            SELECT s.id, s.parent_id, s.title, s.time_created,
                   p.name AS project_name,
                   (SELECT MAX(m.time_created) FROM message m
                    WHERE m.session_id = s.id) AS last_activity_ts,
                   (SELECT MIN(CAST(CASE WHEN json_valid(m.data) = 1
                       THEN json_extract(m.data, '$.time.created') END AS INTEGER))
                    FROM message m WHERE m.session_id = s.id
                      AND CASE WHEN json_valid(m.data) = 1
                               THEN json_extract(m.data, '$.role') END = 'assistant'
                      AND (CAST(COALESCE(CASE WHEN json_valid(m.data) = 1
                                      THEN json_extract(m.data, '$.tokens.input') END, 0) AS INTEGER) > 0
                        OR CAST(COALESCE(CASE WHEN json_valid(m.data) = 1
                                      THEN json_extract(m.data, '$.tokens.output') END, 0) AS INTEGER) > 0
                        OR CAST(COALESCE(CASE WHEN json_valid(m.data) = 1
                                      THEN json_extract(m.data, '$.tokens.cache.read') END, 0) AS INTEGER) > 0
                        OR CAST(COALESCE(CASE WHEN json_valid(m.data) = 1
                                      THEN json_extract(m.data, '$.tokens.cache.write') END, 0) AS INTEGER) > 0)
                   ) AS first_token_activity_ts,
                   EXISTS (SELECT 1 FROM message m WHERE m.session_id = s.id) AS has_messages
            FROM session s
            LEFT JOIN project p ON s.project_id = p.id
            WHERE s.id IN ({placeholders})
              AND EXISTS (
                SELECT 1 FROM message m WHERE m.session_id = s.id
                  AND CASE WHEN json_valid(m.data) = 1
                           THEN json_extract(m.data, '$.role') END = 'assistant'
                  AND (CAST(COALESCE(CASE WHEN json_valid(m.data) = 1
                                  THEN json_extract(m.data, '$.tokens.input') END, 0) AS INTEGER) > 0
                    OR CAST(COALESCE(CASE WHEN json_valid(m.data) = 1
                                  THEN json_extract(m.data, '$.tokens.output') END, 0) AS INTEGER) > 0
                    OR CAST(COALESCE(CASE WHEN json_valid(m.data) = 1
                                  THEN json_extract(m.data, '$.tokens.cache.read') END, 0) AS INTEGER) > 0
                    OR CAST(COALESCE(CASE WHEN json_valid(m.data) = 1
                                  THEN json_extract(m.data, '$.tokens.cache.write') END, 0) AS INTEGER) > 0)
              )
        """
        return conn.execute(query, session_ids).fetchall()

    @staticmethod
    def _metadata_title(row: sqlite3.Row) -> str:
        title = row["title"]
        if title:
            return title[:47] + "..." if len(title) > 50 else title
        return row["id"]

    @classmethod
    def _build_workflow_metadata(
        cls,
        workflow_id: str,
        main_row: sqlite3.Row,
        member_rows: List[sqlite3.Row],
        *,
        is_orphan: bool = False,
        active: bool = False,
        last_activity_ts: Optional[int] = None,
    ) -> Dict[str, Any]:
        return {
            "workflow_id": workflow_id,
            "member_session_ids": [row["id"] for row in member_rows],
            "main_session_id": main_row["id"],
            "project_name": main_row["project_name"] or "Unknown",
            "display_title": cls._metadata_title(main_row),
            "session_count": len(member_rows),
            "sub_agent_count": max(0, len(member_rows) - 1),
            # Milliseconds, from the parent session's message.time_created column.
            "last_activity_ts": last_activity_ts,
            "active": active,
            "is_orphan": is_orphan,
        }

    @classmethod
    def list_recent_workflow_metadata(
        cls, db_path: Optional[Path] = None, limit: int = 5
    ) -> List[Dict[str, Any]]:
        """List recent token-bearing parent workflows using bounded metadata SQL.

        ``limit`` bounds returned workflows, not candidate roots. A missing
        database or non-positive limit produces an empty list. Each call uses
        and closes its own connection; a populated ``last_activity_ts`` is in
        Unix milliseconds.
        """
        if db_path is None:
            db_path = cls.find_database_path()
        if not db_path or not db_path.exists() or limit <= 0:
            return []
        conn = cls._get_connection(db_path)
        try:
            parents = conn.execute(
                """SELECT id FROM session WHERE parent_id IS NULL
                   ORDER BY time_created DESC LIMIT ?""",
                (limit * 5,),
            ).fetchall()
            parent_ids = [row["id"] for row in parents]
            if not parent_ids:
                return []
            placeholders = ",".join("?" for _ in parent_ids)
            child_rows = conn.execute(
                f"SELECT id FROM session WHERE parent_id IN ({placeholders})",
                parent_ids,
            ).fetchall()
            candidate_ids = parent_ids + [row["id"] for row in child_rows]
            metadata = cls._metadata_session_rows(conn, candidate_ids)
            by_id = {row["id"]: row for row in metadata}
            workflows = []
            for parent_id in parent_ids:
                main = by_id.get(parent_id)
                if main is None or not main["has_messages"]:
                    continue
                members = [main] + sorted(
                    (row for row in metadata if row["parent_id"] == parent_id),
                    key=lambda row: (row["time_created"] or 0, row["id"]),
                )
                workflows.append(cls._build_workflow_metadata(parent_id, main, members))
                if len(workflows) >= limit:
                    break
            return workflows
        finally:
            conn.close()

    @classmethod
    def load_workflow_from_metadata(
        cls, metadata: Dict[str, Any], db_path: Optional[Path] = None
    ) -> Optional[Dict[str, Any]]:
        """Hydrate only the sessions selected by a metadata workflow.

        The metadata member order is preserved. A stale/missing main session or
        an invalid metadata payload returns ``None``; unavailable sub-agent rows
        are omitted without loading any sessions outside the selected IDs.
        Missing databases also return ``None``; the method opens and closes its
        own connection and does not cache hydrated sessions.
        """
        if db_path is None:
            db_path = cls.find_database_path()
        if not db_path or not db_path.exists():
            return None
        workflow_id = metadata.get("workflow_id")
        main_session_id = metadata.get("main_session_id")
        member_ids = metadata.get("member_session_ids")
        if not workflow_id or not main_session_id or not isinstance(member_ids, list):
            return None
        if main_session_id not in member_ids:
            return None
        conn = cls._get_connection(db_path)
        try:
            placeholders = ",".join("?" for _ in member_ids)
            if not placeholders:
                return None
            rows = conn.execute(
                f"""SELECT s.*, p.worktree AS project_path, p.name AS project_name
                    FROM session s LEFT JOIN project p ON s.project_id = p.id
                    WHERE s.id IN ({placeholders})""",
                member_ids,
            ).fetchall()
            row_by_id = {row["id"]: row for row in rows}
            main_row = row_by_id.get(main_session_id)
            if main_row is None:
                return None
            loaded_by_id = {}
            for session_id in member_ids:
                row = row_by_id.get(session_id)
                if row is None:
                    continue
                session = cls.load_session_data(conn, row)
                if session is not None:
                    loaded_by_id[session_id] = session
            main_session = loaded_by_id.get(main_session_id)
            if main_session is None:
                return None
            all_sessions = [loaded_by_id[session_id] for session_id in member_ids
                            if session_id in loaded_by_id]
            sub_agents = [session for session in all_sessions if session.session_id != main_session_id]
            return {
                "main_session": main_session,
                "sub_agents": sub_agents,
                "all_sessions": all_sessions,
                "project_name": metadata.get("project_name", main_session.project_name),
                "display_title": metadata.get("display_title", main_session.display_title),
                "session_count": len(all_sessions),
                "sub_agent_count": len(sub_agents),
                "has_sub_agents": bool(sub_agents),
                "workflow_id": workflow_id,
                "is_orphan": bool(metadata.get("is_orphan", False)),
            }
        finally:
            conn.close()

    @classmethod
    def list_active_workflow_metadata(
        cls,
        db_path: Optional[Path] = None,
        active_threshold_minutes: int = 30,
    ) -> List[Dict[str, Any]]:
        """List active workflow metadata without loading message histories.

        ``last_activity_ts`` is the parent's latest ``message.time_created`` for
        normal workflows, or the latest child message for orphan groups, in Unix
        milliseconds. A missing database yields an empty list; each call uses
        its own connection and returns at most ten workflows.
        """
        if db_path is None:
            db_path = cls.find_database_path()
        if not db_path or not db_path.exists():
            return []
        threshold_ms = int(time.time() * 1000) - active_threshold_minutes * 60 * 1000
        conn = cls._get_connection(db_path)
        try:
            parent_rows = conn.execute(
                """SELECT s.id, MAX(m.time_created) AS last_activity_ts
                   FROM session s JOIN message m ON m.session_id = s.id
                   WHERE s.parent_id IS NULL GROUP BY s.id
                   HAVING last_activity_ts > ? ORDER BY last_activity_ts DESC LIMIT 30""",
                (threshold_ms,),
            ).fetchall()
            parent_ids = [row["id"] for row in parent_rows]
            orphan_children = conn.execute(
                """SELECT s.id, s.parent_id, s.time_created, MAX(m.time_created) AS activity_ts
                   FROM session s JOIN message m ON m.session_id = s.id
                   WHERE s.parent_id IS NOT NULL AND m.time_created > ?
                   GROUP BY s.id ORDER BY activity_ts DESC LIMIT 30""",
                (threshold_ms,),
            ).fetchall()
            active_parent_set = set(parent_ids)
            orphan_parent_ids = []
            for child in orphan_children:
                parent_id = child["parent_id"]
                if parent_id not in active_parent_set and parent_id not in orphan_parent_ids:
                    orphan_parent_ids.append(parent_id)

            candidate_ids = list(parent_ids)
            all_roots = parent_ids + orphan_parent_ids
            if all_roots:
                placeholders = ",".join("?" for _ in all_roots)
                child_rows = conn.execute(
                    f"SELECT id FROM session WHERE parent_id IN ({placeholders})",
                    all_roots,
                ).fetchall()
                candidate_ids.extend(row["id"] for row in child_rows)
            metadata = cls._metadata_session_rows(conn, candidate_ids)
            by_id = {row["id"]: row for row in metadata}
            # Roots with recent messages but no positive-token assistant message
            # are not eligible parent workflows. If an active child exists,
            # expose the group's eligible children as a synthetic orphan.
            orphan_parent_ids.extend(
                parent_id
                for parent_id in parent_ids
                if parent_id not in by_id
                and parent_id not in orphan_parent_ids
                and any(child["parent_id"] == parent_id for child in orphan_children)
            )
            workflows = []
            for candidate in parent_rows:
                parent_id = candidate["id"]
                main = by_id.get(parent_id)
                if main is None:
                    continue
                members = [main] + sorted(
                    (row for row in metadata if row["parent_id"] == parent_id),
                    key=lambda row: (row["time_created"] or 0, row["id"]),
                )
                workflows.append(
                    cls._build_workflow_metadata(
                        parent_id, main, members, active=True,
                        last_activity_ts=candidate["last_activity_ts"],
                    )
                )
            for orphan_id in orphan_parent_ids:
                active_child_ids = {
                    child["id"] for child in orphan_children
                    if child["parent_id"] == orphan_id
                }
                members = sorted(
                    (row for row in metadata if row["parent_id"] == orphan_id
                     and row["id"] in active_child_ids),
                    key=lambda row: (row["first_token_activity_ts"] or 0, row["id"]),
                )
                if not members:
                    continue
                workflows.append(
                    cls._build_workflow_metadata(
                        orphan_id, members[0], members, is_orphan=True, active=True,
                        last_activity_ts=max(
                            row["last_activity_ts"] or 0 for row in members
                        ),
                    )
                )
            workflows.sort(
                key=lambda workflow: workflow["last_activity_ts"] or 0,
                reverse=True,
            )
            return workflows[:10]
        finally:
            conn.close()

    @classmethod
    def get_workflow_metadata_by_id(
        cls, workflow_id: str, db_path: Optional[Path] = None
    ) -> Optional[Dict[str, Any]]:
        """Resolve a parent, child, or synthetic orphan workflow ID to metadata.

        Child IDs resolve to their parent workflow; roots without eligible
        parent messages resolve to an orphan group of eligible children. Unknown
        IDs or a missing database return ``None``. The read connection is
        local to this call and is closed before returning.
        """
        if db_path is None:
            db_path = cls.find_database_path()
        if not db_path or not db_path.exists():
            return None
        conn = cls._get_connection(db_path)
        try:
            target = conn.execute(
                "SELECT id, parent_id FROM session WHERE id = ?", (workflow_id,)
            ).fetchone()
            if target is None:
                return None
            main_id = target["id"] if target["parent_id"] is None else target["parent_id"]
            child_ids = conn.execute(
                "SELECT id FROM session WHERE parent_id = ?", (main_id,)
            ).fetchall()
            candidate_ids = [main_id] + [row["id"] for row in child_ids]
            metadata = cls._metadata_session_rows(conn, candidate_ids)
            by_id = {row["id"]: row for row in metadata}
            main_row = by_id.get(main_id)
            if main_row is not None:
                members = [main_row] + sorted(
                    (row for row in metadata if row["parent_id"] == main_id),
                    key=lambda row: (row["time_created"] or 0, row["id"]),
                )
                return cls._build_workflow_metadata(main_id, main_row, members)

            # A root without positive-token assistant messages is represented by
            # its eligible children, just like a synthetic orphan group.
            members = sorted(
                (row for row in metadata if row["parent_id"] == main_id),
                key=lambda row: (row["first_token_activity_ts"] or 0, row["id"]),
            )
            if not members:
                return None
            return cls._build_workflow_metadata(
                main_id,
                members[0],
                members,
                is_orphan=True,
                last_activity_ts=max(row["last_activity_ts"] or 0 for row in members),
            )
        finally:
            conn.close()

    @classmethod
    def _build_workflow_dict(
        cls, conn: sqlite3.Connection, main_session: SessionData
    ) -> Dict[str, Any]:
        """Build workflow payload with parent session and loaded sub-agents."""
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
    def _find_orphan_subagent_workflows(
        cls,
        conn: sqlite3.Connection,
        threshold_ms: int,
        loaded_parent_ids: set,
    ) -> List[Dict[str, Any]]:
        """Find sub-agent workflows whose parents don't have token data.

        Some parent sessions (e.g., ACP sessions) may have messages but no token
        usage, causing them to be filtered out by load_session_data(). This method
        finds sub-agents that should be grouped together under a synthetic workflow.

        Args:
            conn: Database connection
            threshold_ms: Activity threshold in milliseconds
            loaded_parent_ids: Set of parent IDs that were already loaded successfully

        Returns:
            List of workflow dictionaries for orphan sub-agent groups
        """
        if loaded_parent_ids:
            placeholders = ",".join("?" * len(loaded_parent_ids))
            query = f"""
                SELECT s.*, p.worktree as project_path, p.name as project_name
                FROM session s
                LEFT JOIN project p ON s.project_id = p.id
                WHERE s.parent_id IS NOT NULL
                AND s.parent_id NOT IN ({placeholders})
                AND EXISTS (
                    SELECT 1 FROM message m
                    WHERE m.session_id = s.id AND m.time_created > ?
                )
                ORDER BY s.time_created DESC
            """
            params = list(loaded_parent_ids) + [threshold_ms]
        else:
            query = """
                SELECT s.*, p.worktree as project_path, p.name as project_name
                FROM session s
                LEFT JOIN project p ON s.project_id = p.id
                WHERE s.parent_id IS NOT NULL
                AND EXISTS (
                    SELECT 1 FROM message m
                    WHERE m.session_id = s.id AND m.time_created > ?
                )
                ORDER BY s.time_created DESC
            """
            params = [threshold_ms]

        sub_agent_rows = conn.execute(query, params).fetchall()

        sub_agents_by_parent: Dict[str, List[SessionData]] = {}
        for row in sub_agent_rows:
            sub_session = cls.load_session_data(conn, row)
            if sub_session and sub_session.parent_id:
                parent_id: str = sub_session.parent_id
                if parent_id not in sub_agents_by_parent:
                    sub_agents_by_parent[parent_id] = []
                sub_agents_by_parent[parent_id].append(sub_session)

        orphan_workflows = []
        for parent_id, sub_agents in sub_agents_by_parent.items():
            if len(sub_agents) == 0:
                continue

            sub_agents.sort(key=lambda s: s.start_time or datetime.min)
            first_sub = sub_agents[0]

            remaining_subs = sub_agents[1:] if len(sub_agents) > 1 else []

            workflow = {
                "main_session": first_sub,
                "sub_agents": remaining_subs,
                "all_sessions": sub_agents,
                "project_name": first_sub.project_name,
                "display_title": first_sub.display_title
                or f"Orphan workflow ({parent_id[:12]}...)",
                "session_count": len(sub_agents),
                "sub_agent_count": len(remaining_subs),
                "has_sub_agents": len(remaining_subs) > 0,
                "workflow_id": parent_id,
                "is_orphan": True,
            }
            orphan_workflows.append(workflow)

        return orphan_workflows

    @classmethod
    def get_all_active_workflows(
        cls, db_path: Optional[Path] = None, active_threshold_minutes: int = 30
    ) -> List[Dict[str, Any]]:
        """Get all active workflows (parent sessions that are still ongoing).

        A workflow is considered active if its most recent message is within
        active_threshold_minutes (default 30). This avoids relying on time_archived
        which may not be set reliably when sessions end.

        Also handles orphan sub-agents whose parent sessions don't have token data
        (e.g., ACP sessions). These are grouped by parent_id and shown as workflows.

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
            threshold_ms = int(time.time() * 1000) - (
                active_threshold_minutes * 60 * 1000
            )

            parent_rows = conn.execute(
                """
                SELECT s.*, p.worktree as project_path, p.name as project_name,
                       MAX(m.time_created) as last_parent_message_time
                FROM session s
                LEFT JOIN project p ON s.project_id = p.id
                JOIN message m ON m.session_id = s.id
                WHERE s.parent_id IS NULL
                GROUP BY s.id
                HAVING last_parent_message_time > ?
                ORDER BY last_parent_message_time DESC
                LIMIT 30
            """,
                (threshold_ms,),
            ).fetchall()

            active_workflows = []
            loaded_parent_ids = set()

            for parent_row in parent_rows:
                session = cls.load_session_data(conn, parent_row)
                if session and session.files:
                    loaded_parent_ids.add(session.session_id)
                    active_workflows.append(cls._build_workflow_dict(conn, session))

            orphan_workflows = cls._find_orphan_subagent_workflows(
                conn, threshold_ms, loaded_parent_ids
            )
            active_workflows.extend(orphan_workflows)

            return active_workflows[:10]
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

    @classmethod
    def load_tool_usage_for_sessions(
        cls, session_ids: List[str], db_path: Optional[Path] = None
    ) -> List[ToolUsageStats]:
        """Load tool usage statistics for the given sessions.

        Queries the `part` table for tool entries with terminal statuses
        (completed or error) and aggregates counts by tool name.

        Args:
            session_ids: List of session IDs to aggregate tool usage for
            db_path: Path to database (uses default if not provided)

        Returns:
            List of ToolUsageStats sorted by total_calls descending
        """
        if not session_ids:
            return []

        if db_path is None:
            db_path = cls.find_database_path()

        if not db_path or not db_path.exists():
            return []

        conn = cls._get_connection(db_path)
        try:
            # Build placeholders for IN clause
            placeholders = ",".join("?" * len(session_ids))

            # Query tool parts with terminal statuses
            # Use json_valid to protect against malformed JSON
            # Use json_extract to access nested fields in the data column
            query = f"""
                SELECT 
                    json_extract(data, '$.tool') as tool_name,
                    json_extract(data, '$.state.status') as status,
                    COUNT(*) as count
                FROM part
                WHERE session_id IN ({placeholders})
                  AND json_valid(data) = 1
                  AND json_extract(data, '$.type') = 'tool'
                  AND json_extract(data, '$.tool') IS NOT NULL
                  AND json_extract(data, '$.state.status') IN ('completed', 'error')
                GROUP BY tool_name, status
            """

            cursor = conn.execute(query, session_ids)

            # Aggregate by tool name
            tool_data: Dict[str, Dict[str, int]] = {}
            for row in cursor:
                tool_name = row["tool_name"]
                status = row["status"]
                count = row["count"]

                if tool_name not in tool_data:
                    tool_data[tool_name] = {
                        "success": 0,
                        "failure": 0,
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "cache_read_tokens": 0,
                        "cache_write_tokens": 0,
                    }

                if status == "completed":
                    tool_data[tool_name]["success"] += count
                elif status == "error":
                    tool_data[tool_name]["failure"] += count

            # Attribute message-level tokens to tools. OpenCode records tokens on
            # assistant messages, while tool calls are separate part rows. For a
            # message with multiple terminal tool calls, split the message tokens
            # evenly across those calls to avoid double-counting.
            token_query = f"""
                WITH terminal_tools AS (
                    SELECT
                        p.session_id,
                        p.message_id,
                        json_extract(p.data, '$.tool') as tool_name,
                        m.data as message_data
                    FROM part p
                    JOIN message m ON p.message_id = m.id
                    WHERE p.session_id IN ({placeholders})
                      AND json_valid(p.data) = 1
                      AND json_valid(m.data) = 1
                      AND json_extract(p.data, '$.type') = 'tool'
                      AND json_extract(p.data, '$.tool') IS NOT NULL
                      AND json_extract(p.data, '$.state.status') IN ('completed', 'error')
                ),
                message_tool_counts AS (
                    SELECT session_id, message_id, COUNT(*) as tool_count
                    FROM terminal_tools
                    GROUP BY session_id, message_id
                )
                SELECT
                    t.tool_name,
                    SUM(COALESCE(json_extract(t.message_data, '$.tokens.input'), 0) * 1.0 / mtc.tool_count) as input_tokens,
                    SUM(COALESCE(json_extract(t.message_data, '$.tokens.output'), 0) * 1.0 / mtc.tool_count) as output_tokens,
                    SUM(COALESCE(json_extract(t.message_data, '$.tokens.cache.read'), 0) * 1.0 / mtc.tool_count) as cache_read_tokens,
                    SUM(COALESCE(json_extract(t.message_data, '$.tokens.cache.write'), 0) * 1.0 / mtc.tool_count) as cache_write_tokens
                FROM terminal_tools t
                JOIN message_tool_counts mtc
                  ON t.session_id = mtc.session_id
                 AND t.message_id = mtc.message_id
                GROUP BY t.tool_name
            """

            try:
                token_cursor = conn.execute(token_query, session_ids)
                for row in token_cursor:
                    tool_name = row["tool_name"]
                    if tool_name not in tool_data:
                        continue
                    tool_data[tool_name]["input_tokens"] = round(
                        row["input_tokens"] or 0
                    )
                    tool_data[tool_name]["output_tokens"] = round(
                        row["output_tokens"] or 0
                    )
                    tool_data[tool_name]["cache_read_tokens"] = round(
                        row["cache_read_tokens"] or 0
                    )
                    tool_data[tool_name]["cache_write_tokens"] = round(
                        row["cache_write_tokens"] or 0
                    )
            except sqlite3.OperationalError:
                # Legacy/minimal DBs may not have a message table; keep counts.
                pass

            # Build ToolUsageStats list
            stats = []
            for tool_name, counts in tool_data.items():
                total = counts["success"] + counts["failure"]
                stats.append(
                    ToolUsageStats(
                        tool_name=tool_name,
                        total_calls=total,
                        success_count=counts["success"],
                        failure_count=counts["failure"],
                        input_tokens=counts["input_tokens"],
                        output_tokens=counts["output_tokens"],
                        cache_read_tokens=counts["cache_read_tokens"],
                        cache_write_tokens=counts["cache_write_tokens"],
                    )
                )

            # Sort by total_calls descending
            stats.sort(key=lambda s: s.total_calls, reverse=True)

            return stats
        finally:
            conn.close()

    @classmethod
    def load_tool_usage_by_model_for_sessions(
        cls, session_ids: List[str], db_path: Optional[Path] = None
    ) -> List[ModelToolUsage]:
        """Load tool usage statistics grouped by model for the given sessions.

        Queries the `part` table joined with `message` to get model information
        for each tool call. Aggregates counts by model and tool name.

        Args:
            session_ids: List of session IDs to aggregate tool usage for
            db_path: Path to database (uses default if not provided)

        Returns:
            List of ModelToolUsage sorted by total_calls descending
        """
        if not session_ids:
            return []

        if db_path is None:
            db_path = cls.find_database_path()

        if not db_path or not db_path.exists():
            return []

        conn = cls._get_connection(db_path)
        try:
            placeholders = ",".join("?" * len(session_ids))

            query = f"""
                SELECT 
                    COALESCE(
                        json_extract(m.data, '$.modelID'),
                        json_extract(m.data, '$.model.modelID'),
                        'unknown'
                    ) as model_id,
                    COALESCE(NULLIF(json_extract(m.data, '$.agent'), ''), 'main') as agent_name,
                    json_extract(p.data, '$.tool') as tool_name,
                    json_extract(p.data, '$.state.status') as status,
                    COUNT(*) as count
                FROM part p
                JOIN message m ON p.message_id = m.id
                WHERE p.session_id IN ({placeholders})
                  AND json_valid(p.data) = 1
                  AND json_valid(m.data) = 1
                  AND json_extract(p.data, '$.type') = 'tool'
                  AND json_extract(p.data, '$.tool') IS NOT NULL
                  AND json_extract(p.data, '$.state.status') IN ('completed', 'error')
                GROUP BY agent_name, model_id, tool_name, status
            """

            cursor = conn.execute(query, session_ids)

            model_data: Dict[str, Dict[str, Any]] = {}
            for row in cursor:
                model_id = row["model_id"]
                agent_name = row["agent_name"]
                group_key = SessionData.agent_model_key(agent_name, model_id)
                tool_name = row["tool_name"]
                status = row["status"]
                count = row["count"]

                if group_key not in model_data:
                    model_data[group_key] = {
                        "agent_name": agent_name,
                        "model_name": model_id,
                        "tools": {},
                    }
                tools = model_data[group_key]["tools"]
                if tool_name not in tools:
                    tools[tool_name] = {
                        "success": 0,
                        "failure": 0,
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "cache_read_tokens": 0,
                        "cache_write_tokens": 0,
                    }

                if status == "completed":
                    tools[tool_name]["success"] += count
                elif status == "error":
                    tools[tool_name]["failure"] += count

            # Attribute message-level tokens to each model/tool pair. Tokens are
            # stored on assistant messages, not individual tool rows. Split a
            # message's tokens evenly across its terminal tool calls to avoid
            # over-counting when multiple tools share one message.
            token_query = f"""
                WITH terminal_tools AS (
                    SELECT
                        p.session_id,
                        p.message_id,
                        COALESCE(
                            json_extract(m.data, '$.modelID'),
                            json_extract(m.data, '$.model.modelID'),
                            'unknown'
                        ) as model_id,
                        COALESCE(NULLIF(json_extract(m.data, '$.agent'), ''), 'main') as agent_name,
                        json_extract(p.data, '$.tool') as tool_name,
                        m.data as message_data
                    FROM part p
                    JOIN message m ON p.message_id = m.id
                    WHERE p.session_id IN ({placeholders})
                      AND json_valid(p.data) = 1
                      AND json_valid(m.data) = 1
                      AND json_extract(p.data, '$.type') = 'tool'
                      AND json_extract(p.data, '$.tool') IS NOT NULL
                      AND json_extract(p.data, '$.state.status') IN ('completed', 'error')
                ),
                message_tool_counts AS (
                    SELECT session_id, message_id, COUNT(*) as tool_count
                    FROM terminal_tools
                    GROUP BY session_id, message_id
                )
                SELECT
                    t.model_id,
                    t.agent_name,
                    t.tool_name,
                    SUM(COALESCE(json_extract(t.message_data, '$.tokens.input'), 0) * 1.0 / mtc.tool_count) as input_tokens,
                    SUM(COALESCE(json_extract(t.message_data, '$.tokens.output'), 0) * 1.0 / mtc.tool_count) as output_tokens,
                    SUM(COALESCE(json_extract(t.message_data, '$.tokens.cache.read'), 0) * 1.0 / mtc.tool_count) as cache_read_tokens,
                    SUM(COALESCE(json_extract(t.message_data, '$.tokens.cache.write'), 0) * 1.0 / mtc.tool_count) as cache_write_tokens
                FROM terminal_tools t
                JOIN message_tool_counts mtc
                  ON t.session_id = mtc.session_id
                 AND t.message_id = mtc.message_id
                GROUP BY t.agent_name, t.model_id, t.tool_name
            """

            token_cursor = conn.execute(token_query, session_ids)
            for row in token_cursor:
                model_id = row["model_id"]
                agent_name = row["agent_name"]
                group_key = SessionData.agent_model_key(agent_name, model_id)
                tool_name = row["tool_name"]
                if group_key not in model_data:
                    continue
                tools = model_data[group_key]["tools"]
                if tool_name not in tools:
                    continue
                tools[tool_name]["input_tokens"] = round(row["input_tokens"] or 0)
                tools[tool_name]["output_tokens"] = round(row["output_tokens"] or 0)
                tools[tool_name]["cache_read_tokens"] = round(
                    row["cache_read_tokens"] or 0
                )
                tools[tool_name]["cache_write_tokens"] = round(
                    row["cache_write_tokens"] or 0
                )

            result = []
            for group in model_data.values():
                tool_stats = []
                for tool_name, counts in group["tools"].items():
                    total = counts["success"] + counts["failure"]
                    tool_stats.append(
                        ToolUsageStats(
                            tool_name=tool_name,
                            total_calls=total,
                            success_count=counts["success"],
                            failure_count=counts["failure"],
                            input_tokens=counts["input_tokens"],
                            output_tokens=counts["output_tokens"],
                            cache_read_tokens=counts["cache_read_tokens"],
                            cache_write_tokens=counts["cache_write_tokens"],
                        )
                    )
                tool_stats.sort(key=lambda s: s.total_calls, reverse=True)
                result.append(
                    ModelToolUsage(
                        model_name=group["model_name"],
                        agent_name=group["agent_name"],
                        tool_stats=tool_stats,
                    )
                )

            result.sort(key=lambda m: m.total_calls, reverse=True)

            return result
        finally:
            conn.close()

    @classmethod
    def find_matching_models(
        cls, query: str, db_path: Optional[Path] = None
    ) -> List[str]:
        """Find model names matching a query string (case-insensitive substring match).

        Args:
            query: Substring to search for in model names
            db_path: Path to database (uses default if not provided)

        Returns:
            List of distinct model name strings matching the query
        """
        if db_path is None:
            db_path = cls.find_database_path()

        if not db_path or not db_path.exists():
            return []

        conn = cls._get_connection(db_path)
        try:
            cursor = conn.execute(
                """
                SELECT DISTINCT
                    COALESCE(
                        json_extract(m.data, '$.modelID'),
                        json_extract(m.data, '$.model.modelID'),
                        'unknown'
                    ) as model_name
                FROM message m
                WHERE json_valid(m.data) = 1
                  AND json_extract(m.data, '$.role') = 'assistant'
                  AND LOWER(COALESCE(
                        json_extract(m.data, '$.modelID'),
                        json_extract(m.data, '$.model.modelID'),
                        'unknown'
                  )) LIKE ?
                ORDER BY model_name
                """,
                (f"%{query.lower()}%",),
            )
            return [
                row["model_name"] for row in cursor if row["model_name"] != "unknown"
            ]
        finally:
            conn.close()

    @classmethod
    def get_model_detail_stats(
        cls,
        model_name: str,
        pricing_data: Dict[str, Any],
        db_path: Optional[Path] = None,
    ) -> Optional[ModelDetailStats]:
        """Get detailed statistics for a single model.

        Args:
            model_name: Exact model name to query
            pricing_data: Model pricing information for cost calculation
            db_path: Path to database (uses default if not provided)

        Returns:
            ModelDetailStats object or None if no data found
        """
        if db_path is None:
            db_path = cls.find_database_path()

        if not db_path or not db_path.exists():
            return None

        conn = cls._get_connection(db_path)
        try:
            # Query 1: Basic aggregate stats
            row = conn.execute(
                """
                SELECT
                    MIN(json_extract(m.data, '$.time.created')) as first_used,
                    MAX(COALESCE(
                        json_extract(m.data, '$.time.completed'),
                        json_extract(m.data, '$.time.created')
                    )) as last_used,
                    COUNT(DISTINCT m.session_id) as total_sessions,
                    COUNT(DISTINCT date(
                        json_extract(m.data, '$.time.created') / 1000, 'unixepoch'
                    )) as total_days,
                    COUNT(m.id) as total_interactions,
                    SUM(MAX(0, COALESCE(json_extract(m.data, '$.tokens.input'), 0))) as input_tokens,
                    SUM(MAX(0, COALESCE(json_extract(m.data, '$.tokens.output'), 0))) as output_tokens,
                    SUM(MAX(0, COALESCE(json_extract(m.data, '$.tokens.cache.read'), 0))) as cache_read,
                    SUM(MAX(0, COALESCE(json_extract(m.data, '$.tokens.cache.write'), 0))) as cache_write
                FROM message m
                WHERE json_valid(m.data) = 1
                  AND json_extract(m.data, '$.role') = 'assistant'
                  AND COALESCE(
                        json_extract(m.data, '$.modelID'),
                        json_extract(m.data, '$.model.modelID')
                  ) = ?
                """,
                (model_name,),
            ).fetchone()

            if not row or row["total_interactions"] == 0:
                return None

            # Parse timestamps
            first_used = None
            last_used = None
            if row["first_used"]:
                try:
                    first_used = datetime.fromtimestamp(row["first_used"] / 1000)
                except (OSError, ValueError):
                    pass
            if row["last_used"]:
                try:
                    last_used = datetime.fromtimestamp(row["last_used"] / 1000)
                except (OSError, ValueError):
                    pass

            tokens = TokenUsage(
                input=max(0, row["input_tokens"] or 0),
                output=max(0, row["output_tokens"] or 0),
                cache_read=max(0, row["cache_read"] or 0),
                cache_write=max(0, row["cache_write"] or 0),
            )

            # Calculate cost using pricing data
            total_cost = Decimal("0.0")
            model_pricing = FileProcessor.lookup_pricing(
                pricing_data,
                model_id=model_name,
                provider_id=None,
            )
            if model_pricing:
                price_input = getattr(model_pricing, "input", 0) or 0
                price_output = getattr(model_pricing, "output", 0) or 0
                price_cache_read = getattr(model_pricing, "cacheRead", 0) or 0
                price_cache_write = getattr(model_pricing, "cacheWrite", 0) or 0
                total_cost = (
                    Decimal(str(tokens.input))
                    * Decimal(str(price_input))
                    / Decimal("1000000")
                    + Decimal(str(tokens.output))
                    * Decimal(str(price_output))
                    / Decimal("1000000")
                    + Decimal(str(tokens.cache_read))
                    * Decimal(str(price_cache_read))
                    / Decimal("1000000")
                    + Decimal(str(tokens.cache_write))
                    * Decimal(str(price_cache_write))
                    / Decimal("1000000")
                )

            total_sessions = row["total_sessions"]
            total_days = row["total_days"]
            avg_cost_per_day = (
                total_cost / total_days if total_days > 0 else Decimal("0.0")
            )
            avg_cost_per_session = (
                total_cost / total_sessions if total_sessions > 0 else Decimal("0.0")
            )

            # Query 2: Per-interaction output rates for p50 calculation
            rate_cursor = conn.execute(
                """
                SELECT
                    COALESCE(json_extract(m.data, '$.tokens.output'), 0) as output_tokens,
                    json_extract(m.data, '$.time.created') as created,
                    json_extract(m.data, '$.time.completed') as completed,
                    json_extract(m.data, '$.finish') as finish_reason
                FROM message m
                WHERE json_valid(m.data) = 1
                  AND json_extract(m.data, '$.role') = 'assistant'
                  AND COALESCE(
                        json_extract(m.data, '$.modelID'),
                        json_extract(m.data, '$.model.modelID')
                  ) = ?
                """,
                (model_name,),
            )

            interaction_rates = []
            for rate_row in rate_cursor:
                output_tok = rate_row["output_tokens"] or 0
                created_ms = rate_row["created"]
                completed_ms = rate_row["completed"]
                finish = rate_row["finish_reason"]

                if not created_ms or not completed_ms:
                    continue
                duration_ms = completed_ms - created_ms
                if duration_ms <= 0 or output_tok < 100:
                    continue
                # Skip tool-call-only interactions
                if finish == "tool-calls":
                    continue
                rate = output_tok / (duration_ms / 1000)
                interaction_rates.append(rate)

            # Query 3: Tool usage stats
            tool_cursor = conn.execute(
                """
                SELECT
                    json_extract(p.data, '$.tool') as tool_name,
                    COUNT(*) as total_calls,
                    SUM(CASE WHEN json_extract(p.data, '$.state.status') = 'completed'
                        THEN 1 ELSE 0 END) as success,
                    SUM(CASE WHEN json_extract(p.data, '$.state.status') = 'error'
                        THEN 1 ELSE 0 END) as failed
                FROM part p
                JOIN message m ON p.message_id = m.id
                WHERE json_valid(p.data) = 1
                  AND json_valid(m.data) = 1
                  AND json_extract(p.data, '$.type') = 'tool'
                  AND json_extract(p.data, '$.tool') IS NOT NULL
                  AND json_extract(p.data, '$.state.status') IN ('completed', 'error')
                  AND COALESCE(
                        json_extract(m.data, '$.modelID'),
                        json_extract(m.data, '$.model.modelID')
                  ) = ?
                GROUP BY tool_name
                ORDER BY total_calls DESC
                """,
                (model_name,),
            )

            tool_stats = []
            for tool_row in tool_cursor:
                tool_stats.append(
                    ToolUsageStats(
                        tool_name=tool_row["tool_name"],
                        total_calls=tool_row["total_calls"],
                        success_count=tool_row["success"],
                        failure_count=tool_row["failed"],
                    )
                )

            tool_summary = ToolUsageSummary(tool_stats=tool_stats)

            return ModelDetailStats(
                model_name=model_name,
                first_used=first_used,
                last_used=last_used,
                total_sessions=total_sessions,
                total_days_used=total_days,
                total_interactions=row["total_interactions"],
                total_tokens=tokens,
                total_cost=total_cost,
                avg_cost_per_day=avg_cost_per_day,
                avg_cost_per_session=avg_cost_per_session,
                interaction_rates=interaction_rates,
                tool_stats=tool_stats,
                tool_summary=tool_summary,
            )
        finally:
            conn.close()

    @classmethod
    def get_completed_turn_counts(
        cls, session_ids: Sequence[str], db_path: Optional[Path] = None
    ) -> Optional[Dict[str, int]]:
        """Count validated completed user turns by the triggering user's agent.

        The count follows OpenCode v1.18.32 message/part semantics: an assistant
        message completes a turn only when it references a same-session user via
        ``parentID``, has a non-empty non-tool finish reason, has no error, and
        has no disqualifying tool part. User messages require parts and an agent;
        known synthetic-only text prompts and compaction prompts are excluded.
        An absent optional synthetic flag is treated as ordinary text only when
        no auto+overflow compaction marker exists in the supplied histories;
        that marker makes the entire result unavailable because replayed prompts
        may lack synthetic provenance.

        Reads are restricted to the supplied session IDs, with SQLite extracting
        only the fields needed for validation (never message or tool text). An
        empty mapping is a validated zero. ``None`` means data or provenance was
        malformed, incomplete, ambiguous, the database/schema was unavailable,
        or SQLite could not safely evaluate the required JSON fields. The method
        assumes the caller supplies every session in the selected workflow. It
        opens and closes its own connection and keeps no cross-call cache.
        """
        if not session_ids:
            return {}
        ids = list(dict.fromkeys(session_ids))
        if any(not isinstance(session_id, str) or not session_id for session_id in ids):
            return None

        if db_path is None:
            db_path = cls.find_database_path()
        if not db_path or not db_path.exists():
            return None

        placeholders = ",".join("?" for _ in ids)
        conn = cls._get_connection(db_path)
        try:
            existing_sessions = conn.execute(
                f"SELECT id FROM session WHERE id IN ({placeholders})", ids
            ).fetchall()
            if {row["id"] for row in existing_sessions} != set(ids):
                return None
            # CASE guards ensure malformed JSON never reaches json_extract.
            messages = conn.execute(
                f"""
                SELECT id, session_id,
                       CASE WHEN json_valid(data) THEN json_type(data, '$') END AS root_type,
                       CASE WHEN json_valid(data) THEN json_extract(data, '$.role') END AS role,
                       CASE WHEN json_valid(data) THEN json_type(data, '$.role') END AS role_type,
                       CASE WHEN json_valid(data) THEN json_extract(data, '$.parentID') END AS parent_id,
                       CASE WHEN json_valid(data) THEN json_type(data, '$.parentID') END AS parent_type,
                       CASE WHEN json_valid(data) THEN json_extract(data, '$.finish') END AS finish,
                       CASE WHEN json_valid(data) THEN json_type(data, '$.finish') END AS finish_type,
                       CASE WHEN json_valid(data) THEN json_extract(data, '$.agent') END AS agent,
                       CASE WHEN json_valid(data) THEN json_type(data, '$.agent') END AS agent_type,
                       CASE WHEN json_valid(data) THEN json_type(data, '$.error') END AS error_type,
                       CASE WHEN json_valid(data) THEN json_extract(data, '$.error') END AS error_value,
                       CASE WHEN json_valid(data) THEN json_extract(data, '$.type') END AS message_type,
                       CASE WHEN json_valid(data) THEN json_extract(data, '$.auto') END AS auto_flag,
                       CASE WHEN json_valid(data) THEN json_extract(data, '$.overflow') END AS overflow_flag,
                       CASE WHEN json_valid(data) THEN json_extract(data, '$.compaction.auto') END AS compact_auto,
                       CASE WHEN json_valid(data) THEN json_extract(data, '$.compaction.overflow') END AS compact_overflow,
                       json_valid(data) AS valid_json
                FROM message WHERE session_id IN ({placeholders})
                """,
                ids,
            ).fetchall()
            parts = conn.execute(
                f"""
                SELECT id, message_id, session_id,
                       CASE WHEN json_valid(data) THEN json_type(data, '$') END AS root_type,
                       CASE WHEN json_valid(data) THEN json_extract(data, '$.type') END AS part_type,
                       CASE WHEN json_valid(data) THEN json_type(data, '$.type') END AS part_type_type,
                       CASE WHEN json_valid(data) THEN json_type(data, '$.text') END AS text_type,
                       CASE WHEN json_valid(data) THEN length(json_extract(data, '$.text')) END AS text_length,
                       CASE WHEN json_valid(data) THEN json_extract(data, '$.synthetic') END AS synthetic,
                       CASE WHEN json_valid(data) THEN json_type(data, '$.synthetic') END AS synthetic_type,
                       CASE WHEN json_valid(data) THEN json_extract(data, '$.text.synthetic') END AS text_synthetic,
                       CASE WHEN json_valid(data) THEN json_type(data, '$.text.synthetic') END AS text_synthetic_type,
                       CASE WHEN json_valid(data) THEN json_extract(data, '$.metadata.synthetic') END AS metadata_synthetic,
                       CASE WHEN json_valid(data) THEN json_type(data, '$.metadata.synthetic') END AS metadata_synthetic_type,
                       CASE WHEN json_valid(data) THEN json_extract(data, '$.metadata.providerExecuted') END AS provider_executed,
                       CASE WHEN json_valid(data) THEN json_type(data, '$.metadata.providerExecuted') END AS provider_executed_type,
                       CASE WHEN json_valid(data) THEN json_extract(data, '$.state.status') END AS status,
                       CASE WHEN json_valid(data) THEN json_type(data, '$.state.status') END AS status_type,
                       CASE WHEN json_valid(data) THEN json_extract(data, '$.state.metadata.interrupted') END AS interrupted,
                       CASE WHEN json_valid(data) THEN json_type(data, '$.state.metadata.interrupted') END AS interrupted_type,
                       CASE WHEN json_valid(data) THEN json_extract(data, '$.auto') END AS auto_flag,
                       CASE WHEN json_valid(data) THEN json_extract(data, '$.overflow') END AS overflow_flag,
                       CASE WHEN json_valid(data) THEN json_extract(data, '$.compaction.auto') END AS compact_auto,
                       CASE WHEN json_valid(data) THEN json_extract(data, '$.compaction.overflow') END AS compact_overflow,
                       json_valid(data) AS valid_json
                FROM part WHERE session_id IN ({placeholders})
                """,
                ids,
            ).fetchall()

            if any(not row["valid_json"] or row["root_type"] != "object" for row in messages):
                return None
            if any(not row["valid_json"] or row["root_type"] != "object" for row in parts):
                return None

            message_by_id: Dict[str, Any] = {}
            messages_by_session: Dict[str, List[Any]] = {sid: [] for sid in ids}
            for row in messages:
                if not row["id"] or row["id"] in message_by_id:
                    return None
                if row["role_type"] != "text" or row["role"] not in ("user", "assistant"):
                    return None
                message_by_id[row["id"]] = row
                messages_by_session[row["session_id"]].append(row)
                is_compaction = row["message_type"] in ("compaction", "compaction_continue")
                auto = row["auto_flag"] == 1 or row["compact_auto"] == 1
                overflow = row["overflow_flag"] == 1 or row["compact_overflow"] == 1
                if is_compaction:
                    for flag_name, flag_value in (
                        ("auto", row["auto_flag"]),
                        ("overflow", row["overflow_flag"]),
                        ("compaction.auto", row["compact_auto"]),
                        ("compaction.overflow", row["compact_overflow"]),
                    ):
                        if flag_value is not None and flag_value not in (0, 1):
                            return None
                if is_compaction and auto and overflow:
                    return None
                if row["role"] == "user":
                    if row["agent_type"] != "text" or not row["agent"]:
                        return None
                    if not isinstance(row["agent"], str):
                        return None
                else:
                    if row["parent_type"] != "text" or not row["parent_id"]:
                        return None

            for row in messages:
                if row["role"] == "assistant":
                    parent = message_by_id.get(row["parent_id"])
                    if (
                        parent is None
                        or parent["session_id"] != row["session_id"]
                        or parent["role"] != "user"
                    ):
                        return None

            parts_by_message: Dict[str, List[Any]] = {}
            for part in parts:
                if not part["message_id"] or part["message_id"] not in message_by_id:
                    return None
                if message_by_id[part["message_id"]]["session_id"] != part["session_id"]:
                    return None
                if part["part_type_type"] != "text" or not isinstance(part["part_type"], str):
                    return None
                for type_column in (
                    "synthetic_type", "text_synthetic_type", "metadata_synthetic_type"
                ):
                    if part[type_column] not in (None, "true", "false", "null"):
                        return None
                if part["part_type"] == "text" and part["text_type"] not in (
                    "text", "null", None
                ):
                    return None
                parts_by_message.setdefault(part["message_id"], []).append(part)
                if part["part_type"] in ("compaction", "compaction_continue"):
                    auto = part["auto_flag"] == 1 or part["compact_auto"] == 1
                    overflow = part["overflow_flag"] == 1 or part["compact_overflow"] == 1
                    for flag_value in (
                        part["auto_flag"], part["overflow_flag"],
                        part["compact_auto"], part["compact_overflow"],
                    ):
                        if flag_value is not None and flag_value not in (0, 1):
                            return None
                    if auto and overflow:
                        return None

            # Part states are checked before counting, so unknown tool-state
            # variants fail closed instead of being treated as completed.
            tool_parts_by_message: Dict[str, List[Any]] = {}
            for part in parts:
                if part["part_type"] != "tool":
                    if message_by_id[part["message_id"]]["role"] == "user" and part["part_type"] not in {
                        "text", "file", "image", "compaction", "compaction_continue"
                    }:
                        return None
                    continue
                if part["status_type"] != "text" or part["status"] not in {
                    "completed", "error", "running", "pending"
                }:
                    return None
                if part["provider_executed_type"] not in (None, "true", "false"):
                    return None
                if part["interrupted_type"] not in (None, "true", "false"):
                    return None
                tool_parts_by_message.setdefault(part["message_id"], []).append(part)

            # A non-synthetic non-empty text part is the only positive evidence
            # accepted here for an ordinary user-originated prompt.
            user_is_countable: Dict[str, bool] = {}
            for row in messages:
                if row["role"] != "user":
                    continue
                user_parts = parts_by_message.get(row["id"], [])
                if not user_parts:
                    return None
                compaction_only = all(
                    part["part_type"] in ("compaction", "compaction_continue")
                    for part in user_parts
                )
                text_parts = [part for part in user_parts if part["part_type"] == "text"]
                nonempty_text = [part for part in text_parts if (part["text_length"] or 0) > 0]
                for part in nonempty_text:
                    flags = [
                        part["synthetic"], part["text_synthetic"], part["metadata_synthetic"]
                    ]
                    known_flags = [flag for flag in flags if flag is not None]
                    if any(flag not in (0, 1) for flag in known_flags):
                        return None
                    if len(set(known_flags)) > 1:
                        return None
                synthetic_only = bool(nonempty_text) and all(
                    any(
                        flag == 1
                        for flag in (
                            part["synthetic"], part["text_synthetic"],
                            part["metadata_synthetic"],
                        )
                    )
                    for part in nonempty_text
                )
                has_ordinary_text = any(
                    not any(
                        flag == 1
                        for flag in (
                            part["synthetic"], part["text_synthetic"],
                            part["metadata_synthetic"],
                        )
                    )
                    for part in nonempty_text
                )
                if not compaction_only and not synthetic_only and not has_ordinary_text:
                    return None
                user_is_countable[row["id"]] = not compaction_only and not synthetic_only

            candidates_by_parent: Dict[str, List[Any]] = {}
            for row in messages:
                if row["role"] != "assistant":
                    continue
                finish = row["finish"]
                if row["finish_type"] not in (None, "text", "null"):
                    return None
                plausible_complete = bool(finish) and finish not in ("tool-calls", "unknown")
                if not plausible_complete:
                    continue
                parent_id = row["parent_id"]
                parent = message_by_id.get(parent_id)
                if parent is None or parent["session_id"] != row["session_id"] or parent["role"] != "user":
                    return None
                if row["finish_type"] != "text":
                    return None
                if row["error_type"] not in (None, "null") and row["error_value"] is not None:
                    continue
                disqualifying_tool = any(
                    part["provider_executed"] != 1
                    and not (
                        part["status"] == "error"
                        and part["interrupted"] == 1
                    )
                    for part in tool_parts_by_message.get(row["id"], [])
                )
                if not disqualifying_tool and user_is_countable[parent_id]:
                    candidates_by_parent.setdefault(parent_id, []).append(row)

            counts: Dict[str, int] = {}
            for user_id, candidates in candidates_by_parent.items():
                if len(candidates) != 1:
                    return None
                agent = message_by_id[user_id]["agent"]
                counts[agent] = counts.get(agent, 0) + 1
            return counts
        except (sqlite3.Error, TypeError, ValueError):
            return None
        finally:
            conn.close()
