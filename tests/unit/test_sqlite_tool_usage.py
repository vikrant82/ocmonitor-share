"""Tests for SQLite tool usage functionality."""

import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from ocmonitor.models.tool_usage import ToolUsageStats
from ocmonitor.utils.sqlite_utils import SQLiteProcessor


class TestLoadToolUsageForSessions:
    """Tests for SQLiteProcessor.load_tool_usage_for_sessions."""

    @pytest.fixture
    def temp_db(self, tmp_path: Path) -> Path:
        """Create a temporary SQLite database with test data."""
        db_path = tmp_path / "test_opencode.db"
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        
        # Create tables
        conn.execute("""
            CREATE TABLE session (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                parent_id TEXT,
                title TEXT,
                time_created INTEGER NOT NULL,
                time_updated INTEGER NOT NULL
            )
        """)
        
        conn.execute("""
            CREATE TABLE part (
                id TEXT PRIMARY KEY,
                message_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                time_created INTEGER NOT NULL,
                time_updated INTEGER NOT NULL,
                data TEXT NOT NULL
            )
        """)
        
        # Insert test sessions
        conn.execute(
            "INSERT INTO session (id, project_id, parent_id, title, time_created, time_updated) VALUES (?, ?, ?, ?, ?, ?)",
            ("ses_test1", "proj_1", None, "Test Session 1", 1000, 2000)
        )
        conn.execute(
            "INSERT INTO session (id, project_id, parent_id, title, time_created, time_updated) VALUES (?, ?, ?, ?, ?, ?)",
            ("ses_test2", "proj_1", None, "Test Session 2", 3000, 4000)
        )
        
        # Insert tool parts for session 1
        # bash: 3 completed, 1 error
        for i, status in enumerate(["completed", "completed", "completed", "error"]):
            data = json.dumps({
                "type": "tool",
                "tool": "bash",
                "state": {"status": status}
            })
            conn.execute(
                "INSERT INTO part (id, message_id, session_id, time_created, time_updated, data) VALUES (?, ?, ?, ?, ?, ?)",
                (f"prt_bash_{i}", "msg_1", "ses_test1", 1000 + i, 1000 + i, data)
            )
        
        # read: 2 completed
        for i in range(2):
            data = json.dumps({
                "type": "tool",
                "tool": "read",
                "state": {"status": "completed"}
            })
            conn.execute(
                "INSERT INTO part (id, message_id, session_id, time_created, time_updated, data) VALUES (?, ?, ?, ?, ?, ?)",
                (f"prt_read_{i}", "msg_1", "ses_test1", 2000 + i, 2000 + i, data)
            )
        
        # edit: 1 completed, 2 error
        for i, status in enumerate(["completed", "error", "error"]):
            data = json.dumps({
                "type": "tool",
                "tool": "edit",
                "state": {"status": status}
            })
            conn.execute(
                "INSERT INTO part (id, message_id, session_id, time_created, time_updated, data) VALUES (?, ?, ?, ?, ?, ?)",
                (f"prt_edit_{i}", "msg_1", "ses_test1", 3000 + i, 3000 + i, data)
            )
        
        # Insert tool parts for session 2
        # bash: 1 completed
        data = json.dumps({
            "type": "tool",
            "tool": "bash",
            "state": {"status": "completed"}
        })
        conn.execute(
            "INSERT INTO part (id, message_id, session_id, time_created, time_updated, data) VALUES (?, ?, ?, ?, ?, ?)",
            ("prt_bash_s2", "msg_2", "ses_test2", 3000, 3000, data)
        )
        
        # Insert non-tool parts (should be ignored)
        data = json.dumps({
            "type": "text",
            "text": "Some text"
        })
        conn.execute(
            "INSERT INTO part (id, message_id, session_id, time_created, time_updated, data) VALUES (?, ?, ?, ?, ?, ?)",
            ("prt_text", "msg_1", "ses_test1", 4000, 4000, data)
        )
        
        # Insert running tool (should be ignored)
        data = json.dumps({
            "type": "tool",
            "tool": "bash",
            "state": {"status": "running"}
        })
        conn.execute(
            "INSERT INTO part (id, message_id, session_id, time_created, time_updated, data) VALUES (?, ?, ?, ?, ?, ?)",
            ("prt_running", "msg_1", "ses_test1", 5000, 5000, data)
        )
        
        conn.commit()
        conn.close()
        
        return db_path

    def test_load_tool_usage_aggregates_correctly(self, temp_db: Path):
        """Test that tool usage is aggregated correctly across sessions."""
        stats = SQLiteProcessor.load_tool_usage_for_sessions(
            ["ses_test1", "ses_test2"], temp_db
        )
        
        assert len(stats) == 3
        
        # bash should be first (most calls: 4 completed from ses_test1 + 1 completed from ses_test2 + 1 error = 5 total)
        assert stats[0].tool_name == "bash"
        assert stats[0].total_calls == 5  # 4 completed + 1 error (running is excluded)
        assert stats[0].success_count == 4  # 3 from ses_test1 + 1 from ses_test2
        assert stats[0].failure_count == 1
        assert stats[0].success_rate == 80.0
        
        # edit: 1 completed + 2 error = 3 total
        edit_stat = next(s for s in stats if s.tool_name == "edit")
        assert edit_stat.total_calls == 3
        assert edit_stat.success_count == 1
        assert edit_stat.failure_count == 2
        assert edit_stat.success_rate == pytest.approx(33.33, rel=0.01)
        
        # read: 2 completed
        read_stat = next(s for s in stats if s.tool_name == "read")
        assert read_stat.total_calls == 2
        assert read_stat.success_count == 2
        assert read_stat.failure_count == 0
        assert read_stat.success_rate == 100.0

    def test_load_tool_usage_excludes_running_status(self, temp_db: Path):
        """Test that running status is excluded from stats."""
        stats = SQLiteProcessor.load_tool_usage_for_sessions(
            ["ses_test1"], temp_db
        )
        
        # The running bash command should be excluded
        # ses_test1 has: 3 bash completed, 1 bash error, 1 bash running
        # So bash should have 4 total (3 completed + 1 error), not 5
        bash_stat = next(s for s in stats if s.tool_name == "bash")
        assert bash_stat.total_calls == 4  # Would be 5 if running was included

    def test_load_tool_usage_empty_session_ids(self, temp_db: Path):
        """Test that empty session IDs returns empty list."""
        stats = SQLiteProcessor.load_tool_usage_for_sessions([], temp_db)
        assert stats == []

    def test_load_tool_usage_nonexistent_session(self, temp_db: Path):
        """Test that nonexistent session returns empty list."""
        stats = SQLiteProcessor.load_tool_usage_for_sessions(
            ["ses_nonexistent"], temp_db
        )
        assert stats == []

    def test_load_tool_usage_missing_db_path(self, tmp_path: Path):
        """Test that missing database path returns empty list."""
        with patch.object(SQLiteProcessor, 'find_database_path', return_value=None):
            stats = SQLiteProcessor.load_tool_usage_for_sessions(["ses_test"])
            assert stats == []

    def test_load_tool_usage_sorts_by_total_calls_descending(self, temp_db: Path):
        """Test that results are sorted by total calls descending."""
        stats = SQLiteProcessor.load_tool_usage_for_sessions(
            ["ses_test1", "ses_test2"], temp_db
        )
        
        # Verify sorted by total_calls descending
        for i in range(len(stats) - 1):
            assert stats[i].total_calls >= stats[i + 1].total_calls

    def test_load_tool_usage_ignores_malformed_json(self, tmp_path: Path):
        """Test that malformed JSON in data column is safely ignored."""
        db_path = tmp_path / "test_malformed.db"
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        
        # Create tables
        conn.execute("""
            CREATE TABLE session (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                parent_id TEXT,
                title TEXT,
                time_created INTEGER NOT NULL,
                time_updated INTEGER NOT NULL
            )
        """)
        
        conn.execute("""
            CREATE TABLE part (
                id TEXT PRIMARY KEY,
                message_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                time_created INTEGER NOT NULL,
                time_updated INTEGER NOT NULL,
                data TEXT NOT NULL
            )
        """)
        
        # Insert test session
        conn.execute(
            "INSERT INTO session (id, project_id, parent_id, title, time_created, time_updated) VALUES (?, ?, ?, ?, ?, ?)",
            ("ses_malformed", "proj_1", None, "Malformed Test", 1000, 2000)
        )
        
        # Insert valid tool
        data = json.dumps({
            "type": "tool",
            "tool": "bash",
            "state": {"status": "completed"}
        })
        conn.execute(
            "INSERT INTO part (id, message_id, session_id, time_created, time_updated, data) VALUES (?, ?, ?, ?, ?, ?)",
            ("prt_valid", "msg_1", "ses_malformed", 1000, 1000, data)
        )
        
        # Insert malformed JSON (should be ignored without error)
        conn.execute(
            "INSERT INTO part (id, message_id, session_id, time_created, time_updated, data) VALUES (?, ?, ?, ?, ?, ?)",
            ("prt_malformed", "msg_1", "ses_malformed", 2000, 2000, "{not valid json}")
        )
        
        # Insert malformed JSON that looks like tool (should be ignored)
        conn.execute(
            "INSERT INTO part (id, message_id, session_id, time_created, time_updated, data) VALUES (?, ?, ?, ?, ?, ?)",
            ("prt_malformed2", "msg_1", "ses_malformed", 3000, 3000, '{"type": "tool", "tool": "edit"')
        )
        
        conn.commit()
        conn.close()
        
        # Should not raise and should only count valid tool
        stats = SQLiteProcessor.load_tool_usage_for_sessions(
            ["ses_malformed"], db_path
        )
        
        assert len(stats) == 1
        assert stats[0].tool_name == "bash"
        assert stats[0].total_calls == 1

    def test_load_tool_usage_ignores_null_tool_name(self, tmp_path: Path):
        """Test that rows with null tool name are safely ignored."""
        db_path = tmp_path / "test_null_tool.db"
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        
        # Create tables
        conn.execute("""
            CREATE TABLE session (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                parent_id TEXT,
                title TEXT,
                time_created INTEGER NOT NULL,
                time_updated INTEGER NOT NULL
            )
        """)
        
        conn.execute("""
            CREATE TABLE part (
                id TEXT PRIMARY KEY,
                message_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                time_created INTEGER NOT NULL,
                time_updated INTEGER NOT NULL,
                data TEXT NOT NULL
            )
        """)
        
        # Insert test session
        conn.execute(
            "INSERT INTO session (id, project_id, parent_id, title, time_created, time_updated) VALUES (?, ?, ?, ?, ?, ?)",
            ("ses_null", "proj_1", None, "Null Tool Test", 1000, 2000)
        )
        
        # Insert valid tool
        data = json.dumps({
            "type": "tool",
            "tool": "read",
            "state": {"status": "completed"}
        })
        conn.execute(
            "INSERT INTO part (id, message_id, session_id, time_created, time_updated, data) VALUES (?, ?, ?, ?, ?, ?)",
            ("prt_valid", "msg_1", "ses_null", 1000, 1000, data)
        )
        
        # Insert tool with null tool name (missing 'tool' field)
        data = json.dumps({
            "type": "tool",
            "state": {"status": "completed"}
        })
        conn.execute(
            "INSERT INTO part (id, message_id, session_id, time_created, time_updated, data) VALUES (?, ?, ?, ?, ?, ?)",
            ("prt_null_tool", "msg_1", "ses_null", 2000, 2000, data)
        )
        
        conn.commit()
        conn.close()
        
        # Should not raise and should only count valid tool
        stats = SQLiteProcessor.load_tool_usage_for_sessions(
            ["ses_null"], db_path
        )
        
        assert len(stats) == 1
        assert stats[0].tool_name == "read"


class TestToolUsageStatsModel:
    """Tests for ToolUsageStats model."""

    def test_success_rate_calculation(self):
        """Test success rate is calculated correctly."""
        stats = ToolUsageStats(
            tool_name="test",
            total_calls=10,
            success_count=8,
            failure_count=2
        )
        assert stats.success_rate == 80.0

    def test_success_rate_zero_total(self):
        """Test success rate is 0 when total is 0."""
        stats = ToolUsageStats(tool_name="test")
        assert stats.success_rate == 0.0

    def test_default_values(self):
        """Test default values are set correctly."""
        stats = ToolUsageStats(tool_name="test")
        assert stats.total_calls == 0
        assert stats.success_count == 0
        assert stats.failure_count == 0
