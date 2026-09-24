"""Focused tests for validated SQLite completed-turn counts."""

import json
import sqlite3
from pathlib import Path

import pytest

from ocmonitor.utils.sqlite_utils import SQLiteProcessor


def _database(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE session (
            id TEXT PRIMARY KEY, project_id TEXT NOT NULL, parent_id TEXT,
            title TEXT, time_created INTEGER NOT NULL, time_updated INTEGER NOT NULL
        );
        CREATE TABLE message (
            id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
            time_created INTEGER NOT NULL, time_updated INTEGER NOT NULL, data TEXT NOT NULL
        );
        CREATE INDEX message_session_id_idx ON message(session_id);
        CREATE TABLE part (
            id TEXT PRIMARY KEY, message_id TEXT NOT NULL, session_id TEXT NOT NULL,
            time_created INTEGER NOT NULL, time_updated INTEGER NOT NULL, data TEXT NOT NULL
        );
        CREATE INDEX part_session_id_idx ON part(session_id);
        """
    )
    return conn


class TurnFixture:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.next_time = 1

    def session(self, session_id: str, parent_id=None):
        self.conn.execute(
            "INSERT INTO session VALUES (?, 'project', ?, ?, ?, ?)",
            (session_id, parent_id, session_id, self.next_time, self.next_time),
        )
        self.next_time += 1

    def message(self, session_id: str, message_id: str, data: dict):
        timestamp = self.next_time
        self.next_time += 1
        self.conn.execute(
            "INSERT INTO message VALUES (?, ?, ?, ?, ?)",
            (message_id, session_id, timestamp, timestamp, json.dumps(data)),
        )

    def part(self, session_id: str, message_id: str, data: dict, part_id=None):
        timestamp = self.next_time
        self.next_time += 1
        self.conn.execute(
            "INSERT INTO part VALUES (?, ?, ?, ?, ?, ?)",
            (part_id or f"part-{timestamp}", message_id, session_id, timestamp, timestamp, json.dumps(data)),
        )

    def user(self, session_id: str, message_id: str, agent="build", synthetic=False):
        self.message(session_id, message_id, {"role": "user", "agent": agent})
        self.part(
            session_id,
            message_id,
            {"type": "text", "text": "prompt", "synthetic": synthetic},
        )

    def assistant(self, session_id: str, message_id: str, parent_id: str, finish="stop", error=None):
        data = {"role": "assistant", "parentID": parent_id}
        if finish is not None:
            data["finish"] = finish
        if error is not None:
            data["error"] = error
        self.message(session_id, message_id, data)


@pytest.fixture
def turns_db(tmp_path: Path):
    path = tmp_path / "turns.db"
    conn = _database(path)
    fixture = TurnFixture(conn)
    try:
        yield fixture, path
    finally:
        conn.close()


def test_counts_turn_once_after_tool_handoffs_and_attributes_child_agent(turns_db):
    fixture, path = turns_db
    fixture.session("root")
    fixture.session("child", "root")

    fixture.user("root", "u1", "build")
    fixture.assistant("root", "a1", "u1", "tool-calls")
    fixture.part(
        "root", "a1", {"type": "tool", "state": {"status": "completed"}}, "p1"
    )
    fixture.assistant("root", "a2", "u1", "tool-calls")
    fixture.part(
        "root", "a2", {"type": "tool", "state": {"status": "completed"}}, "p2"
    )
    fixture.assistant("root", "a3", "u1", "stop")

    fixture.user("child", "u2", "explore")
    fixture.assistant("child", "a4", "u2", "end_turn")
    fixture.user("child", "u3", "explore")
    fixture.assistant("child", "a5", "u3", None)  # incomplete
    fixture.user("root", "u4", "review")
    fixture.assistant("root", "a6", "u4", "stop", error={"name": "Failure"})

    fixture.conn.commit()
    assert SQLiteProcessor.get_completed_turn_counts(["root", "child"], path) == {
        "build": 1,
        "explore": 1,
    }


def test_excludes_synthetic_only_user_prompts(turns_db):
    fixture, path = turns_db
    fixture.session("root")
    fixture.user("root", "u1", "build", synthetic=True)
    fixture.assistant("root", "a1", "u1")
    fixture.conn.commit()

    assert SQLiteProcessor.get_completed_turn_counts(["root"], path) == {}


def test_counts_ordinary_user_text_when_optional_synthetic_flag_is_absent(turns_db):
    fixture, path = turns_db
    fixture.session("root")
    fixture.message("root", "u1", {"role": "user", "agent": "build"})
    fixture.part("root", "u1", {"type": "text", "text": "prompt"})
    fixture.assistant("root", "a1", "u1")
    fixture.conn.commit()

    assert SQLiteProcessor.get_completed_turn_counts(["root"], path) == {"build": 1}


def test_auto_overflow_compaction_makes_entire_workflow_unavailable(turns_db):
    fixture, path = turns_db
    fixture.session("root")
    fixture.user("root", "u1")
    fixture.assistant("root", "a1", "u1")
    fixture.message(
        "root",
        "compact",
        {"role": "assistant", "type": "compaction", "auto": True, "overflow": True},
    )
    fixture.conn.commit()

    assert SQLiteProcessor.get_completed_turn_counts(["root"], path) is None


def test_unflagged_prompt_with_auto_overflow_replay_marker_is_unavailable(turns_db):
    fixture, path = turns_db
    fixture.session("root")
    fixture.message("root", "u1", {"role": "user", "agent": "build"})
    fixture.part("root", "u1", {"type": "text", "text": "replayed prompt"})
    fixture.assistant("root", "a1", "u1")
    fixture.message(
        "root",
        "compact",
        {"role": "assistant", "type": "compaction", "auto": True, "overflow": True},
    )
    fixture.conn.commit()

    assert SQLiteProcessor.get_completed_turn_counts(["root"], path) is None


@pytest.mark.parametrize("case", ["malformed", "missing_parent", "duplicate", "missing_agent", "missing_parts", "unknown_tool_state"])
def test_ambiguous_records_make_workflow_unavailable(turns_db, case):
    fixture, path = turns_db
    fixture.session("root")
    if case == "missing_agent":
        fixture.message("root", "u1", {"role": "user"})
        fixture.part("root", "u1", {"type": "text", "text": "prompt", "synthetic": False})
        fixture.assistant("root", "a1", "u1")
    elif case == "missing_parts":
        fixture.message("root", "u1", {"role": "user", "agent": "build"})
        fixture.assistant("root", "a1", "u1")
    elif case == "missing_parent":
        fixture.user("root", "u1")
        fixture.assistant("root", "a1", "missing-user")
    elif case == "duplicate":
        fixture.user("root", "u1")
        fixture.assistant("root", "a1", "u1")
        fixture.assistant("root", "a2", "u1")
    elif case == "unknown_tool_state":
        fixture.user("root", "u1")
        fixture.assistant("root", "a1", "u1", "stop")
        fixture.part("root", "a1", {"type": "tool", "state": {"status": "mystery"}})
    elif case == "malformed":
        fixture.conn.execute(
            "INSERT INTO message VALUES ('bad', 'root', 100, 100, '{not json')"
        )
    fixture.conn.commit()

    assert SQLiteProcessor.get_completed_turn_counts(["root"], path) is None


def test_valid_workflow_with_no_completed_turns_returns_empty_mapping(turns_db):
    fixture, path = turns_db
    fixture.session("root")
    fixture.user("root", "u1")
    fixture.assistant("root", "a1", "u1", "tool-calls")
    fixture.conn.commit()

    assert SQLiteProcessor.get_completed_turn_counts(["root"], path) == {}
