import json
import sqlite3
import time
from pathlib import Path

from ocmonitor.utils.sqlite_utils import SQLiteProcessor


def _assistant_message(tokens: int = 10) -> str:
    return json.dumps(
        {
            "role": "assistant",
            "tokens": {"input": tokens, "output": 0, "cache": {"write": 0, "read": 0}},
            "time": {
                "created": int(time.time() * 1000),
                "completed": int(time.time() * 1000),
            },
        }
    )


def _create_base_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE project (
            id TEXT PRIMARY KEY,
            worktree TEXT,
            name TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE session (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            parent_id TEXT,
            title TEXT,
            time_created INTEGER NOT NULL,
            time_updated INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE message (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            time_created INTEGER NOT NULL,
            time_updated INTEGER NOT NULL,
            data TEXT NOT NULL
        )
        """
    )


def test_get_all_active_workflows_orders_by_latest_parent_activity(tmp_path: Path):
    db_path = tmp_path / "opencode.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _create_base_schema(conn)

    now_ms = int(time.time() * 1000)

    conn.execute(
        "INSERT INTO project (id, worktree, name) VALUES (?, ?, ?)",
        ("proj", "/tmp/project", "project"),
    )

    # This parent is created earlier, but has the newest parent message.
    conn.execute(
        "INSERT INTO session (id, project_id, parent_id, title, time_created, time_updated) VALUES (?, ?, ?, ?, ?, ?)",
        (
            "older-parent",
            "proj",
            None,
            "Older Parent",
            now_ms - 10_000,
            now_ms - 10_000,
        ),
    )
    conn.execute(
        "INSERT INTO message (id, session_id, time_created, time_updated, data) VALUES (?, ?, ?, ?, ?)",
        (
            "msg-older-new",
            "older-parent",
            now_ms - 1_000,
            now_ms - 1_000,
            _assistant_message(),
        ),
    )

    # This parent is created later, but has an older parent message.
    conn.execute(
        "INSERT INTO session (id, project_id, parent_id, title, time_created, time_updated) VALUES (?, ?, ?, ?, ?, ?)",
        ("newer-parent", "proj", None, "Newer Parent", now_ms - 2_000, now_ms - 2_000),
    )
    conn.execute(
        "INSERT INTO message (id, session_id, time_created, time_updated, data) VALUES (?, ?, ?, ?, ?)",
        (
            "msg-newer-old",
            "newer-parent",
            now_ms - 5_000,
            now_ms - 5_000,
            _assistant_message(),
        ),
    )

    conn.commit()
    conn.close()

    workflows = SQLiteProcessor.get_all_active_workflows(
        db_path=db_path,
        active_threshold_minutes=60,
    )

    assert [w["workflow_id"] for w in workflows[:2]] == ["older-parent", "newer-parent"]


def test_get_recent_workflows(tmp_path: Path):
    db_path = tmp_path / "opencode.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _create_base_schema(conn)

    now_ms = int(time.time() * 1000)

    conn.execute(
        "INSERT INTO project (id, worktree, name) VALUES (?, ?, ?)",
        ("proj", "/tmp/project", "project"),
    )

    # Insert 6 parent sessions
    for i in range(1, 7):
        conn.execute(
            "INSERT INTO session (id, project_id, parent_id, title, time_created, time_updated) VALUES (?, ?, ?, ?, ?, ?)",
            (f"parent-{i}", "proj", None, f"Parent {i}", now_ms - i * 1000, now_ms - i * 1000),
        )
        # Parent 5 has NO messages (empty session)
        if i != 5:
            conn.execute(
                "INSERT INTO message (id, session_id, time_created, time_updated, data) VALUES (?, ?, ?, ?, ?)",
                (f"msg-{i}", f"parent-{i}", now_ms - i * 1000, now_ms - i * 1000, _assistant_message()),
            )

    conn.commit()
    conn.close()

    # Get recent workflows with a limit of 3
    # Expected: should get parent-1, parent-2, parent-3 (ordered DESC by time_created, skipping parent-5)
    workflows = SQLiteProcessor.get_recent_workflows(db_path=db_path, limit=3)

    assert len(workflows) == 3
    assert [w["workflow_id"] for w in workflows] == ["parent-1", "parent-2", "parent-3"]

    # Get recent workflows with a limit of 10
    # Expected: should get parent-1, parent-2, parent-3, parent-4, parent-6 (skipping parent-5)
    all_workflows = SQLiteProcessor.get_recent_workflows(db_path=db_path, limit=10)
    assert len(all_workflows) == 5
    assert [w["workflow_id"] for w in all_workflows] == ["parent-1", "parent-2", "parent-3", "parent-4", "parent-6"]


def test_get_workflow_by_id(tmp_path: Path):
    db_path = tmp_path / "opencode.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _create_base_schema(conn)

    now_ms = int(time.time() * 1000)

    conn.execute(
        "INSERT INTO project (id, worktree, name) VALUES (?, ?, ?)",
        ("proj", "/tmp/project", "project"),
    )

    # Insert parent session and a sub-agent session
    conn.execute(
        "INSERT INTO session (id, project_id, parent_id, title, time_created, time_updated) VALUES (?, ?, ?, ?, ?, ?)",
        ("parent-id", "proj", None, "Parent Title", now_ms, now_ms),
    )
    conn.execute(
        "INSERT INTO message (id, session_id, time_created, time_updated, data) VALUES (?, ?, ?, ?, ?)",
        ("msg-1", "parent-id", now_ms, now_ms, _assistant_message()),
    )

    conn.execute(
        "INSERT INTO session (id, project_id, parent_id, title, time_created, time_updated) VALUES (?, ?, ?, ?, ?, ?)",
        ("sub-id", "proj", "parent-id", "Sub Title", now_ms + 1000, now_ms + 1000),
    )
    conn.execute(
        "INSERT INTO message (id, session_id, time_created, time_updated, data) VALUES (?, ?, ?, ?, ?)",
        ("msg-2", "sub-id", now_ms + 1000, now_ms + 1000, _assistant_message()),
    )

    conn.commit()
    conn.close()

    # Resolve by parent workflow ID
    wf = SQLiteProcessor.get_workflow_by_id("parent-id", db_path=db_path)
    assert wf is not None
    assert wf["workflow_id"] == "parent-id"
    assert len(wf["all_sessions"]) == 2

    # Resolve by sub-agent ID
    wf_sub = SQLiteProcessor.get_workflow_by_id("sub-id", db_path=db_path)
    assert wf_sub is not None
    assert wf_sub["workflow_id"] == "parent-id"  # Maps back to parent's workflow

    # Resolve non-existent ID
    wf_none = SQLiteProcessor.get_workflow_by_id("non-existent", db_path=db_path)
    assert wf_none is None


def test_metadata_workflows_use_sql_metadata_only_and_include_children(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "opencode.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _create_base_schema(conn)
    now_ms = int(time.time() * 1000)
    conn.execute("INSERT INTO project VALUES (?, ?, ?)", ("proj", "/tmp/project", "Project"))
    sessions = [
        ("parent", None, "Parent title", now_ms),
        ("child", "parent", "Child title", now_ms + 1),
        ("orphan-child-a", "missing-parent", "First child", now_ms + 2),
        ("orphan-child-b", "missing-parent", "Second child", now_ms + 3),
        ("later-created-parent", None, "Later created", now_ms + 10),
    ]
    for session_id, parent_id, title, created in sessions:
        conn.execute(
            "INSERT INTO session VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, "proj", parent_id, title, created, created),
        )
        conn.execute(
            "INSERT INTO message VALUES (?, ?, ?, ?, ?)",
            (f"msg-{session_id}", session_id,
             now_ms - 1_000 if session_id == "later-created-parent" else created,
             created, _assistant_message()),
        )
    conn.execute(
        "INSERT INTO session VALUES (?, ?, NULL, ?, ?, ?)",
        ("empty-parent", "proj", "Empty Parent", now_ms - 500, now_ms - 500),
    )
    conn.execute(
        "INSERT INTO session VALUES (?, ?, ?, ?, ?, ?)",
        ("orphan-existing", "proj", "empty-parent", "Existing child", now_ms - 400, now_ms - 400),
    )
    conn.execute(
        "INSERT INTO message VALUES (?, ?, ?, ?, ?)",
        ("msg-orphan-existing", "orphan-existing", now_ms - 400, now_ms - 400, _assistant_message()),
    )
    conn.commit()
    conn.close()

    def unexpected(*args, **kwargs):
        raise AssertionError("metadata lookup must not hydrate sessions/workflows")

    monkeypatch.setattr(SQLiteProcessor, "load_session_data", unexpected)
    monkeypatch.setattr(SQLiteProcessor, "_build_workflow_dict", unexpected)

    recent = SQLiteProcessor.list_recent_workflow_metadata(db_path=db_path, limit=2)
    assert [w["workflow_id"] for w in recent] == [
        "later-created-parent", "parent"
    ]
    assert recent[1]["member_session_ids"] == ["parent", "child"]
    assert recent[1]["session_count"] == 2
    assert recent[1]["sub_agent_count"] == 1
    assert recent[1]["display_title"] == "Parent title"

    active = SQLiteProcessor.list_active_workflow_metadata(
        db_path=db_path, active_threshold_minutes=30
    )
    assert [w["workflow_id"] for w in active[:3]] == [
        "missing-parent", "parent", "empty-parent"
    ]
    parent_workflow = next(w for w in active if w["workflow_id"] == "parent")
    orphan_workflow = next(w for w in active if w["workflow_id"] == "missing-parent")
    assert parent_workflow["member_session_ids"] == ["parent", "child"]
    assert parent_workflow["active"] is True
    assert parent_workflow["is_orphan"] is False
    assert parent_workflow["last_activity_ts"] == now_ms
    assert orphan_workflow["member_session_ids"] == ["orphan-child-a", "orphan-child-b"]
    assert orphan_workflow["main_session_id"] == "orphan-child-a"
    assert orphan_workflow["is_orphan"] is True
    assert orphan_workflow["last_activity_ts"] == now_ms + 3

    selected = SQLiteProcessor.get_workflow_metadata_by_id("child", db_path=db_path)
    assert selected is not None
    assert selected["workflow_id"] == "parent"
    assert selected["member_session_ids"] == ["parent", "child"]
    selected_orphan = SQLiteProcessor.get_workflow_metadata_by_id(
        "orphan-child-b", db_path=db_path
    )
    assert selected_orphan is not None
    assert selected_orphan["workflow_id"] == "missing-parent"
    assert selected_orphan["is_orphan"] is True
    assert selected_orphan["last_activity_ts"] == now_ms + 3

    # Resolve the synthetic workflow by its root ID and refresh children without
    # querying any sessions outside that root's indexed parent_id group.
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "INSERT INTO session VALUES (?, ?, ?, ?, ?, ?)",
        ("orphan-child-new", "proj", "empty-parent", "New child", now_ms + 4, now_ms + 4),
    )
    conn.execute(
        "INSERT INTO message VALUES (?, ?, ?, ?, ?)",
        ("msg-orphan-child-new", "orphan-child-new", now_ms + 4, now_ms + 4, _assistant_message()),
    )
    conn.commit()
    conn.close()
    resolved_synthetic = SQLiteProcessor.get_workflow_metadata_by_id(
        "empty-parent", db_path=db_path
    )
    assert resolved_synthetic is not None
    assert resolved_synthetic["workflow_id"] == "empty-parent"
    assert resolved_synthetic["is_orphan"] is True
    assert resolved_synthetic["member_session_ids"] == [
        "orphan-existing", "orphan-child-new"
    ]
    assert resolved_synthetic["last_activity_ts"] == now_ms + 4


def test_metadata_queries_limit_message_eligibility_to_candidate_sessions(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "opencode.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _create_base_schema(conn)
    conn.execute("CREATE INDEX session_parent_id_idx ON session(parent_id)")
    conn.execute("CREATE INDEX message_session_id_idx ON message(session_id)")
    now_ms = int(time.time() * 1000)
    conn.execute("INSERT INTO project VALUES (?, ?, ?)", ("proj", "/tmp/project", "Project"))
    # Two recent roots with a single child; irrelevant older roots and messages
    # must not be passed to the JSON/token eligibility query.
    for session_id, parent_id, created in (
        ("root-new", None, now_ms),
        ("child-new", "root-new", now_ms + 1),
        ("root-older", None, now_ms - 1_000),
    ):
        conn.execute(
            "INSERT INTO session VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, "proj", parent_id, session_id, created, created),
        )
        conn.execute(
            "INSERT INTO message VALUES (?, ?, ?, ?, ?)",
            (f"msg-{session_id}", session_id, created, created, _assistant_message()),
        )
    for index in range(100):
        session_id = f"irrelevant-{index}"
        created = now_ms - 100_000 - index
        conn.execute(
            "INSERT INTO session VALUES (?, ?, NULL, ?, ?, ?)",
            (session_id, "proj", session_id, created, created),
        )
        conn.execute(
            "INSERT INTO message VALUES (?, ?, ?, ?, ?)",
            (f"msg-{session_id}", session_id, created, created, _assistant_message()),
        )
    conn.commit()
    conn.close()

    original = SQLiteProcessor._metadata_session_rows.__func__
    inspected_ids = []

    def recording_metadata_rows(cls, connection, session_ids):
        inspected_ids.extend(session_ids)
        return original(cls, connection, session_ids)

    monkeypatch.setattr(
        SQLiteProcessor, "_metadata_session_rows", classmethod(recording_metadata_rows)
    )
    result = SQLiteProcessor.list_recent_workflow_metadata(db_path=db_path, limit=1)
    assert result[0]["workflow_id"] == "root-new"
    assert {"root-new", "child-new", "root-older"}.issubset(inspected_ids)
    assert len(inspected_ids) == 6  # limit*5 roots, plus the selected root's child
    assert sum(session_id.startswith("irrelevant-") for session_id in inspected_ids) == 3

    # Ensure the indexed lookup paths are available to candidate/child queries.
    check = sqlite3.connect(db_path)
    child_plan = check.execute(
        "EXPLAIN QUERY PLAN SELECT id FROM session WHERE parent_id = ?", ("root-new",)
    ).fetchall()
    message_plan = check.execute(
        "EXPLAIN QUERY PLAN SELECT data FROM message WHERE session_id = ?", ("root-new",)
    ).fetchall()
    check.close()
    assert any("session_parent_id_idx" in row[3] for row in child_plan)
    assert any("message_session_id_idx" in row[3] for row in message_plan)


def test_active_metadata_groups_child_of_recent_zero_token_parent_as_orphan(tmp_path: Path):
    db_path = tmp_path / "opencode.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _create_base_schema(conn)
    now_ms = int(time.time() * 1000)
    conn.execute("INSERT INTO project VALUES (?, ?, ?)", ("proj", "/tmp/project", "Project"))
    conn.execute(
        "INSERT INTO session VALUES (?, ?, NULL, ?, ?, ?)",
        ("noneligible-root", "proj", "Empty root", now_ms, now_ms),
    )
    zero_token = json.dumps(
        {"role": "assistant", "tokens": {"input": 0, "output": 0}}
    )
    conn.execute(
        "INSERT INTO message VALUES (?, ?, ?, ?, ?)",
        ("root-zero-msg", "noneligible-root", now_ms, now_ms, zero_token),
    )
    conn.execute(
        "INSERT INTO session VALUES (?, ?, ?, ?, ?, ?)",
        ("active-child", "proj", "noneligible-root", "Child", now_ms, now_ms),
    )
    conn.execute(
        "INSERT INTO message VALUES (?, ?, ?, ?, ?)",
        ("child-msg", "active-child", now_ms + 1, now_ms + 1, _assistant_message()),
    )
    conn.commit()
    conn.close()

    result = SQLiteProcessor.list_active_workflow_metadata(
        db_path=db_path, active_threshold_minutes=30
    )
    assert len(result) == 1
    assert result[0]["workflow_id"] == "noneligible-root"
    assert result[0]["member_session_ids"] == ["active-child"]
    assert result[0]["main_session_id"] == "active-child"
    assert result[0]["is_orphan"] is True
    assert result[0]["last_activity_ts"] == now_ms + 1


def test_metadata_queries_ignore_malformed_and_zero_token_messages(tmp_path: Path):
    db_path = tmp_path / "opencode.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _create_base_schema(conn)
    now_ms = int(time.time() * 1000)
    conn.execute("INSERT INTO project VALUES (?, ?, ?)", ("proj", "/tmp/project", "Project"))
    for session_id, data in (
        ("malformed", "{"),
        ("zero", json.dumps({"role": "assistant", "tokens": {"input": 0}})),
        ("good", _assistant_message()),
    ):
        conn.execute(
            "INSERT INTO session VALUES (?, ?, NULL, ?, ?, ?)",
            (session_id, "proj", session_id, now_ms, now_ms),
        )
        conn.execute(
            "INSERT INTO message VALUES (?, ?, ?, ?, ?)",
            (f"msg-{session_id}", session_id, now_ms, now_ms, data),
        )
    conn.commit()
    conn.close()

    recent = SQLiteProcessor.list_recent_workflow_metadata(db_path=db_path, limit=5)
    assert [workflow["workflow_id"] for workflow in recent] == ["good"]
    zero_metadata = SQLiteProcessor.get_workflow_metadata_by_id("zero", db_path=db_path)
    assert zero_metadata is None


def test_load_workflow_from_metadata_hydrates_only_selected_members(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "opencode.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _create_base_schema(conn)
    now_ms = int(time.time() * 1000)
    conn.execute("INSERT INTO project VALUES (?, ?, ?)", ("proj", "/tmp/project", "Project"))

    def add_session(session_id, parent_id, title, message_data):
        conn.execute(
            "INSERT INTO session VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, "proj", parent_id, title, now_ms, now_ms),
        )
        if message_data is not None:
            conn.execute(
                "INSERT INTO message VALUES (?, ?, ?, ?, ?)",
                (f"msg-{session_id}", session_id, now_ms, now_ms, message_data),
            )

    add_session("parent", None, "Parent", _assistant_message())
    add_session("child-a", "parent", "Child A", _assistant_message())
    add_session("child-b", "parent", "Child B", _assistant_message())
    # Existing parent has no token-bearing assistant interaction, so metadata
    # for this workflow uses a child as its main session.
    add_session("empty-parent", None, "Empty Parent", None)
    add_session("orphan-a", "empty-parent", "Orphan A", _assistant_message())
    add_session("orphan-b", "empty-parent", "Orphan B", _assistant_message())
    add_session("unselected", None, "Unselected", _assistant_message())
    conn.commit()
    conn.close()

    loaded_ids = []
    original_loader = SQLiteProcessor.load_session_data.__func__

    def recording_loader(cls, connection, row):
        loaded_ids.append(row["id"])
        return original_loader(cls, connection, row)

    monkeypatch.setattr(SQLiteProcessor, "load_session_data", classmethod(recording_loader))

    metadata = SQLiteProcessor.get_workflow_metadata_by_id("parent", db_path=db_path)
    assert metadata is not None
    hydrated = SQLiteProcessor.load_workflow_from_metadata(metadata, db_path=db_path)
    assert hydrated is not None
    assert hydrated["workflow_id"] == "parent"
    assert [session.session_id for session in hydrated["all_sessions"]] == [
        "parent", "child-a", "child-b"
    ]
    assert hydrated["main_session"].session_id == "parent"
    assert hydrated["display_title"] == metadata["display_title"]
    assert hydrated["project_name"] == metadata["project_name"]
    assert loaded_ids == ["parent", "child-a", "child-b"]

    loaded_ids.clear()
    child_metadata = SQLiteProcessor.get_workflow_metadata_by_id("child-b", db_path=db_path)
    assert child_metadata is not None
    child_hydrated = SQLiteProcessor.load_workflow_from_metadata(
        child_metadata, db_path=db_path
    )
    assert child_hydrated is not None
    assert child_hydrated["workflow_id"] == "parent"
    assert child_hydrated["main_session"].session_id == "parent"
    assert loaded_ids == ["parent", "child-a", "child-b"]

    loaded_ids.clear()
    orphan_metadata = {
        "workflow_id": "empty-parent",
        "main_session_id": "orphan-a",
        "member_session_ids": ["orphan-a", "orphan-b"],
        "project_name": "Project",
        "display_title": "Orphan A",
        "is_orphan": True,
    }
    orphan_hydrated = SQLiteProcessor.load_workflow_from_metadata(
        orphan_metadata, db_path=db_path
    )
    assert orphan_hydrated is not None
    assert orphan_hydrated["workflow_id"] == "empty-parent"
    assert orphan_hydrated["main_session"].session_id == "orphan-a"
    assert orphan_hydrated["is_orphan"] is True
    assert [session.session_id for session in orphan_hydrated["all_sessions"]] == [
        "orphan-a", "orphan-b"
    ]
    assert loaded_ids == ["orphan-a", "orphan-b"]

    missing_main = dict(metadata, main_session_id="missing", member_session_ids=["missing"])
    assert SQLiteProcessor.load_workflow_from_metadata(missing_main, db_path=db_path) is None
