"""Loading-boundary tests for pinned live refresh and workflow pickers.

These tests exercise the public picker entry points and data-source seams. They
intentionally make hydration APIs fail so metadata-only discovery cannot regress
into loading interaction histories just to display a choice.
"""

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from rich.console import Console

from ocmonitor.services.live_monitor import LiveMonitor
from ocmonitor.utils.file_utils import FileProcessor
from ocmonitor.utils.sqlite_utils import SQLiteProcessor
import ocmonitor.services.live_monitor as live_monitor_module


def _file_session_metadata(session_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        session_id=session_id,
        session_path=Path("/sessions") / session_id,
        agent=None,
        project_name="project",
        start_time=datetime(2025, 1, 1),
        end_time=None,
        display_title=f"Title {session_id}",
        last_activity_ts=1_735_689_600.0,
    )


def _metadata_only_failure(*args, **kwargs):
    raise AssertionError("picker hydrated session interaction history")


class TestMetadataOnlyWorkflowPicker:
    def test_file_picker_discovers_metadata_without_hydrating_sessions(
        self, monkeypatch, tmp_path
    ):
        discovered = [_file_session_metadata("file-workflow")]
        discover = patch.object(
            FileProcessor, "discover_session_metadata", return_value=discovered
        )
        monkeypatch.setattr(FileProcessor, "load_all_sessions", _metadata_only_failure)
        monitor = LiveMonitor(pricing_data={}, init_from_db=False)
        monkeypatch.setattr(monitor.console, "input", lambda _: "1")
        monkeypatch.setattr(monitor, "_print_workflow_picker_table", lambda *_: None)

        with discover as discover_mock:
            selected = monitor.pick_file_workflow(str(tmp_path))

        assert selected == "file-workflow"
        discover_mock.assert_called_once_with(str(tmp_path), limit=50)

    def test_sqlite_picker_discovers_metadata_without_hydrating_sessions(
        self, monkeypatch, tmp_path
    ):
        db_path = tmp_path / "opencode.db"
        db_path.touch()
        metadata = {
            "workflow_id": "sqlite-workflow",
            "main_session_id": "sqlite-workflow",
            "member_session_ids": ["sqlite-workflow", "sqlite-subagent"],
            "display_title": "SQLite title",
            "project_name": "project",
            "session_count": 2,
            "sub_agent_count": 1,
            "last_activity_ts": 1_735_689_600_000,
        }
        monkeypatch.setattr(SQLiteProcessor, "find_database_path", lambda: db_path)
        active = patch.object(
            SQLiteProcessor, "list_active_workflow_metadata", return_value=[]
        )
        recent = patch.object(
            SQLiteProcessor, "list_recent_workflow_metadata", return_value=[metadata]
        )
        monkeypatch.setattr(
            SQLiteProcessor, "get_all_active_workflows", _metadata_only_failure
        )
        monkeypatch.setattr(
            SQLiteProcessor, "get_recent_workflows", _metadata_only_failure
        )
        monkeypatch.setattr(SQLiteProcessor, "get_workflow_by_id", _metadata_only_failure)
        monkeypatch.setattr(SQLiteProcessor, "load_session_data", _metadata_only_failure)
        monitor = LiveMonitor(pricing_data={}, init_from_db=False)
        monkeypatch.setattr(monitor.console, "input", lambda _: "1")
        monkeypatch.setattr(monitor, "_print_workflow_picker_table", lambda *_: None)

        with active, recent as recent_mock:
            selected = monitor.pick_sqlite_workflow()

        assert selected == "sqlite-workflow"
        recent_mock.assert_called_once_with(db_path, limit=5)


class TestPinnedRefreshLoadingScope:
    """Pinned refresh must not fall back to eager workflow enumeration."""

    def test_file_pinned_refresh_uses_selected_workflow_without_grouping_others(
        self, monkeypatch, tmp_path
    ):
        selected = _file_session_metadata("selected")
        other = _file_session_metadata("other")
        discovered = patch.object(
            FileProcessor,
            "discover_session_metadata",
            return_value=[selected, other],
        )
        monkeypatch.setattr(FileProcessor, "load_all_sessions", _metadata_only_failure)
        monkeypatch.setattr(
            FileProcessor, "load_sessions_by_id",
            lambda _path, ids: [SimpleNamespace(session_id=ids[0])],
        )
        monitor = LiveMonitor(pricing_data={}, init_from_db=False)
        monkeypatch.setattr(
            monitor.session_grouper, "group_sessions",
            lambda sessions: [SimpleNamespace(workflow_id=sessions[0].session_id)],
        )

        with discovered:
            # The selected-only entry point is expected to return just the
            # pinned workflow, even when discovery sees unrelated metadata.
            workflows = monitor._get_file_active_workflows(
                str(tmp_path), selected_session_id="selected"
            )

        assert [workflow.workflow_id for workflow in workflows] == ["selected"]

    def test_sqlite_pinned_refresh_does_not_hydrate_unselected_workflows(
        self, monkeypatch, tmp_path
    ):
        db_path = tmp_path / "opencode.db"
        db_path.touch()
        selected = {
            "workflow_id": "selected",
            "main_session_id": "selected",
            "member_session_ids": ["selected"],
            "display_title": "Selected",
            "project_name": "project",
            "session_count": 1,
            "sub_agent_count": 0,
            "last_activity_ts": 1_735_689_600_000,
            "active": True,
            "is_orphan": True,
        }
        other = {**selected, "workflow_id": "other", "main_session_id": "other"}
        monkeypatch.setattr(SQLiteProcessor, "find_database_path", lambda: db_path)
        monkeypatch.setattr(
            SQLiteProcessor,
            "list_active_workflow_metadata",
            lambda *_args, **_kwargs: [selected, other],
        )
        monkeypatch.setattr(
            SQLiteProcessor, "list_recent_workflow_metadata", lambda *_args, **_kwargs: []
        )
        monkeypatch.setattr(
            SQLiteProcessor, "get_all_active_workflows", _metadata_only_failure
        )
        hydrate = patch.object(
            SQLiteProcessor, "load_workflow_from_metadata",
            return_value={"workflow_id": "selected"},
        )
        monitor = LiveMonitor(pricing_data={}, init_from_db=False)

        with hydrate as hydrate_mock:
            workflows = monitor._get_sqlite_active_workflows(selected_session_id="selected")

        assert [workflow["workflow_id"] for workflow in workflows] == ["selected"]
        assert hydrate_mock.call_args.args[0]["workflow_id"] == "selected"


class TestLiveLoopLoadingScope:
    class _Live:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def update(self, *_args, **_kwargs):
            pass

        def stop(self):
            pass

        def start(self, **_kwargs):
            pass

    @staticmethod
    def _workflow(workflow_id):
        session = SimpleNamespace(session_id=workflow_id)
        return SimpleNamespace(
            workflow_id=workflow_id,
            main_session=SimpleNamespace(session_id=workflow_id),
            all_sessions=[session],
            has_sub_agents=False,
            session_count=1,
            sub_agent_count=0,
        )

    @staticmethod
    def _candidate(workflow_id, activity):
        member = SimpleNamespace(session_id=workflow_id)
        return SimpleNamespace(
            workflow_id=workflow_id,
            all_sessions=[member],
            main_session=member,
            display_title=workflow_id,
            project_name="project",
            session_count=1,
            sub_agent_count=0,
            last_activity_ts=activity,
            end_time=None,
        )

    @staticmethod
    def _sqlite_candidate(workflow_id, activity):
        return {
            "workflow_id": workflow_id,
            "main_session_id": workflow_id,
            "member_session_ids": [workflow_id],
            "display_title": workflow_id,
            "project_name": "project",
            "session_count": 1,
            "sub_agent_count": 0,
            "last_activity_ts": activity,
            "active": True,
            "is_orphan": False,
        }

    def test_file_timer_refresh_hydrates_only_initially_selected_workflow(
        self, monkeypatch, tmp_path
    ):
        monitor = LiveMonitor(pricing_data={}, init_from_db=False)
        candidates = [self._candidate("selected", 2), self._candidate("other", 1)]
        hydrate = patch.object(
            monitor, "_hydrate_file_metadata_workflow",
            side_effect=lambda _path, metadata: self._workflow(metadata.workflow_id),
        )
        monkeypatch.setattr(monitor, "_get_file_workflow_metadata", lambda *_a, **_k: candidates)
        monkeypatch.setattr(monitor.session_grouper, "group_session_metadata", lambda *_a, **_k: candidates)
        monkeypatch.setattr(FileProcessor, "refresh_session_metadata", lambda _path, cache, **_kwargs: cache)
        monkeypatch.setattr(monitor, "_generate_workflow_dashboard", lambda *_a, **_k: "view")
        monkeypatch.setattr(monitor, "_poll_live_switch_command", lambda: None)
        commands = iter([None, "q"])
        monkeypatch.setattr(monitor, "_poll_live_switch_command", lambda: next(commands))
        monkeypatch.setattr(monitor, "_enable_raw_input_mode", lambda: True)
        monkeypatch.setattr(live_monitor_module, "Live", self._Live)

        with hydrate as hydrate_mock:
            monitor.start_monitoring(str(tmp_path), refresh_interval=0, interactive_switch=True)

        assert [call.args[1].workflow_id for call in hydrate_mock.call_args_list] == [
            "selected", "selected"
        ]
        assert monitor._get_file_workflow_metadata  # metadata provider remains separate

    def test_file_live_switch_refreshes_metadata_then_hydrates_only_target(
        self, monkeypatch, tmp_path
    ):
        monitor = LiveMonitor(pricing_data={}, init_from_db=False)
        selected = self._candidate("selected", 2)
        other = self._candidate("other", 1)
        candidates = [selected, other]
        discover = patch.object(
            monitor, "_get_file_workflow_metadata", return_value=candidates
        )
        hydrated = patch.object(
            monitor, "_hydrate_file_metadata_workflow",
            side_effect=lambda _path, metadata: self._workflow(metadata.workflow_id),
        )
        monkeypatch.setattr(monitor, "_generate_workflow_dashboard", lambda *_a, **_k: "view")
        commands = iter(["l", "q"])
        monkeypatch.setattr(monitor, "_poll_live_switch_command", lambda: next(commands))
        monkeypatch.setattr(monitor, "_pick_workflow_during_live", lambda *_a, **_k: "other")
        monkeypatch.setattr(monitor, "_enable_raw_input_mode", lambda: True)
        monkeypatch.setattr(live_monitor_module, "Live", self._Live)

        with discover as discover_mock, hydrated as hydrate_mock:
            monitor.start_monitoring(str(tmp_path), refresh_interval=60, interactive_switch=True)

        assert discover_mock.call_count == 2  # startup snapshot plus explicit l refresh
        assert [call.args[1].workflow_id for call in hydrate_mock.call_args_list] == [
            "selected", "other"
        ]

    def test_sqlite_timer_refresh_hydrates_only_selected_metadata(self, monkeypatch):
        monitor = LiveMonitor(pricing_data={}, init_from_db=False)
        selected = self._sqlite_candidate("selected", 2)
        other = self._sqlite_candidate("other", 1)
        monkeypatch.setattr(SQLiteProcessor, "find_database_path", lambda: Path("/tmp/db"))
        discover = patch.object(monitor, "_get_sqlite_workflow_metadata", return_value=[selected, other])
        hydrate = patch.object(
            monitor, "_hydrate_sqlite_metadata_workflow",
            side_effect=lambda metadata, _db: {"workflow_id": metadata["workflow_id"],
                                               "main_session": SimpleNamespace(session_id=metadata["workflow_id"]),
                                               "all_sessions": [SimpleNamespace(session_id=metadata["workflow_id"])],
                                               "has_sub_agents": False, "session_count": 1,
                                               "sub_agent_count": 0},
        )
        refreshed_selected = {**selected, "member_session_ids": ["selected", "spawned-child"], "session_count": 2}
        monkeypatch.setattr(SQLiteProcessor, "get_workflow_metadata_by_id", lambda workflow_id, _db: {**refreshed_selected, "workflow_id": workflow_id})
        monkeypatch.setattr(monitor, "_generate_sqlite_workflow_dashboard", lambda *_a, **_k: "view")
        commands = iter([None, "q"])
        monkeypatch.setattr(monitor, "_poll_live_switch_command", lambda: next(commands))
        monkeypatch.setattr(monitor, "_enable_raw_input_mode", lambda: True)
        monkeypatch.setattr(live_monitor_module, "Live", self._Live)

        with discover as discover_mock, hydrate as hydrate_mock:
            monitor.start_sqlite_workflow_monitoring(refresh_interval=0, interactive_switch=True)

        assert [call.args[0]["member_session_ids"] for call in hydrate_mock.call_args_list] == [
            ["selected"], ["selected", "spawned-child"],
        ]
        discover_mock.assert_called_once()

    def test_sqlite_orphan_survives_repeated_refresh_using_metadata_snapshot(
        self, monkeypatch
    ):
        monitor = LiveMonitor(pricing_data={}, init_from_db=False)
        orphan = {
            **self._sqlite_candidate("missing-parent", 0),
            "main_session_id": "orphan-child-a",
            "member_session_ids": ["orphan-child-a", "orphan-child-b"],
            "is_orphan": True,
            "last_activity_ts": None,
        }
        refreshed_orphan = {**orphan, "member_session_ids": [
            "orphan-child-a", "orphan-child-b", "orphan-child-c"
        ]}
        monkeypatch.setattr(SQLiteProcessor, "find_database_path", lambda: Path("/tmp/db"))
        discover = patch.object(monitor, "_get_sqlite_workflow_metadata", return_value=[orphan])
        hydration_ids = []

        def hydrate(metadata, _db):
            hydration_ids.append((metadata["workflow_id"], list(metadata["member_session_ids"])))
            return {
                "workflow_id": metadata["workflow_id"],
                "main_session": SimpleNamespace(session_id=metadata["main_session_id"]),
                "all_sessions": [SimpleNamespace(session_id=item) for item in metadata["member_session_ids"]],
                "has_sub_agents": True,
                "session_count": 2,
                "sub_agent_count": 1,
            }

        monkeypatch.setattr(monitor, "_hydrate_sqlite_metadata_workflow", hydrate)
        monkeypatch.setattr(SQLiteProcessor, "get_workflow_metadata_by_id", lambda workflow_id, _db: refreshed_orphan)
        monkeypatch.setattr(monitor, "_generate_sqlite_workflow_dashboard", lambda *_a, **_k: "view")
        commands = iter([None, None, "q"])
        monkeypatch.setattr(monitor, "_poll_live_switch_command", lambda: next(commands))
        monkeypatch.setattr(monitor, "_enable_raw_input_mode", lambda: True)
        monkeypatch.setattr(live_monitor_module, "Live", self._Live)

        with discover as discover_mock:
            monitor.start_sqlite_workflow_monitoring(
                refresh_interval=0, selected_session_id="orphan-child-a", interactive_switch=True
            )

        assert hydration_ids == [
            ("missing-parent", ["orphan-child-a", "orphan-child-b"]),
            ("missing-parent", ["orphan-child-a", "orphan-child-b", "orphan-child-c"]),
            ("missing-parent", ["orphan-child-a", "orphan-child-b", "orphan-child-c"]),
        ]
        discover_mock.assert_called_once()

    def test_recent_turn_refresh_reloads_selected_only_without_candidate_scan(
        self, monkeypatch, tmp_path
    ):
        monitor = LiveMonitor(pricing_data={}, init_from_db=False)
        selected = self._candidate("selected", 2)
        other = self._candidate("other", 1)
        monkeypatch.setattr(monitor, "_get_file_workflow_metadata", lambda *_a, **_k: [selected, other])
        monkeypatch.setattr(monitor.session_grouper, "group_session_metadata", lambda *_a, **_k: [selected, other])
        monkeypatch.setattr(FileProcessor, "refresh_session_metadata", lambda _path, cache, **_kwargs: cache)
        hydrate = patch.object(
            monitor, "_hydrate_file_metadata_workflow",
            side_effect=lambda _path, metadata: self._workflow(metadata.workflow_id),
        )
        inspect = patch.object(monitor, "_inspect_recent_turns_during_live", side_effect=lambda _live, _workflow, _title, _interactive, **kwargs: kwargs["refresh_workflow"]())
        monkeypatch.setattr(monitor, "_generate_workflow_dashboard", lambda *_a, **_k: "view")
        commands = iter(["t", "q"])
        monkeypatch.setattr(monitor, "_poll_live_switch_command", lambda: next(commands))
        monkeypatch.setattr(monitor, "_enable_raw_input_mode", lambda: True)
        monkeypatch.setattr(live_monitor_module, "Live", self._Live)

        with hydrate as hydrate_mock, inspect:
            monitor.start_monitoring(str(tmp_path), refresh_interval=60, interactive_switch=True)

        assert [call.args[1].workflow_id for call in hydrate_mock.call_args_list] == [
            "selected", "selected"
        ]

    @pytest.mark.parametrize("refresh_via_turns", [False, True])
    def test_file_refresh_discovers_new_child_without_requery_or_unrelated_hydration(
        self, monkeypatch, tmp_path, refresh_via_turns
    ):
        monitor = LiveMonitor(pricing_data={}, init_from_db=False)
        selected = self._candidate("selected", 2)
        other = self._candidate("other", 1)
        discover = patch.object(
            monitor, "_get_file_workflow_metadata", return_value=[selected, other]
        )
        child = _file_session_metadata("ses_child")
        child = SimpleNamespace(**{**child.__dict__, "agent": "subagent"})

        def refresh_metadata(_path, cache, limit=None):
            cache.entries[child.session_id] = child
            return cache

        monkeypatch.setattr(FileProcessor, "refresh_session_metadata", refresh_metadata)

        def group_metadata(sessions):
            by_id = {item.session_id: item for item in sessions}
            root = by_id["selected"]
            return [
                SimpleNamespace(
                    workflow_id="selected",
                    all_sessions=[root, *([by_id["ses_child"]] if "ses_child" in by_id else [])],
                    end_time=None,
                ),
                SimpleNamespace(workflow_id="other", all_sessions=[by_id["other"]], end_time=None),
            ]

        monkeypatch.setattr(monitor.session_grouper, "group_session_metadata", group_metadata)
        hydration_ids = []

        def hydrate(_path, metadata):
            hydration_ids.append([item.session_id for item in metadata.all_sessions])
            return self._workflow(metadata.workflow_id)

        monkeypatch.setattr(monitor, "_hydrate_file_metadata_workflow", hydrate)
        monkeypatch.setattr(monitor, "_generate_workflow_dashboard", lambda *_a, **_k: "view")
        if refresh_via_turns:
            monkeypatch.setattr(
                monitor, "_inspect_recent_turns_during_live",
                lambda _live, _workflow, _title, _interactive, **kwargs: kwargs["refresh_workflow"](),
            )
        commands = iter(["t", "q"] if refresh_via_turns else [None, "q"])
        monkeypatch.setattr(monitor, "_poll_live_switch_command", lambda: next(commands))
        monkeypatch.setattr(monitor, "_enable_raw_input_mode", lambda: True)
        monkeypatch.setattr(live_monitor_module, "Live", self._Live)

        with discover as discover_mock:
            monitor.start_monitoring(
                str(tmp_path), refresh_interval=0 if not refresh_via_turns else 60,
                interactive_switch=True,
            )

        discover_mock.assert_called_once()
        assert hydration_ids == [["selected"], ["selected", "ses_child"]]

    def test_file_live_refresh_finds_child_outside_candidate_limit_without_old_parses(
        self, monkeypatch, tmp_path
    ):
        import json
        import os

        monitor = LiveMonitor(pricing_data={}, init_from_db=False)

        def write_session(session_id, agent, created):
            session_dir = tmp_path / session_id
            session_dir.mkdir()
            (session_dir / "inter_0001.json").write_text(json.dumps({
                "agent": agent,
                "tokens": {"input": 1},
                "time": {"created": created, "completed": created + 1000},
                "path": {"cwd": "/work/project"},
            }))
            return session_dir

        selected_dir = write_session("ses_selected", "main", 1700000000000)
        os.utime(selected_dir, (500, 500))
        old_dirs = [
            write_session(f"ses_old_{index}", "main", 1700000000000 + index)
            for index in range(10)
        ]
        for index, path in enumerate(old_dirs):
            os.utime(path, (400 - index, 400 - index))

        selected = _file_session_metadata("ses_selected")
        selected = SimpleNamespace(**{**selected.__dict__, "session_path": selected_dir})
        candidate = SimpleNamespace(
            workflow_id="ses_selected", all_sessions=[selected], main_session=selected,
            display_title="selected", project_name="project", session_count=1,
            sub_agent_count=0, last_activity_ts=1, end_time=None,
        )
        startup_candidates = [candidate]
        for index, old_dir in enumerate(old_dirs):
            old_metadata = _file_session_metadata(f"ses_old_{index}")
            old_metadata = SimpleNamespace(**{**old_metadata.__dict__, "session_path": old_dir})
            startup_candidates.append(SimpleNamespace(
                workflow_id=old_metadata.session_id, all_sessions=[old_metadata],
                main_session=old_metadata, display_title=old_metadata.session_id,
                project_name="project", session_count=1, sub_agent_count=0,
                last_activity_ts=1, end_time=None,
            ))
        monkeypatch.setattr(monitor, "_get_file_workflow_metadata", lambda *_a, **_k: startup_candidates)

        def group_metadata(sessions):
            by_id = {item.session_id: item for item in sessions}
            return [SimpleNamespace(
                workflow_id="ses_selected",
                all_sessions=[by_id["ses_selected"]] + ([by_id["ses_child"]] if "ses_child" in by_id else []),
                end_time=None,
            )]

        monkeypatch.setattr(monitor.session_grouper, "group_session_metadata", group_metadata)
        parsed = []
        original = FileProcessor._discover_session_directory_metadata

        def recording_parser(path):
            parsed.append(Path(path).name)
            return original(path)

        monkeypatch.setattr(FileProcessor, "_discover_session_directory_metadata", recording_parser)
        hydrated = []

        def hydrate(_path, metadata):
            ids = [item.session_id for item in metadata.all_sessions]
            hydrated.append(ids)
            return self._workflow(metadata.workflow_id)

        monkeypatch.setattr(monitor, "_hydrate_file_metadata_workflow", hydrate)
        monkeypatch.setattr(monitor, "_generate_workflow_dashboard", lambda *_a, **_k: "view")
        commands = iter([None, "q"])
        monkeypatch.setattr(monitor, "_poll_live_switch_command", lambda: next(commands))
        monkeypatch.setattr(monitor, "_enable_raw_input_mode", lambda: True)
        monkeypatch.setattr(live_monitor_module, "Live", self._Live)

        def add_child():
            child_dir = write_session("ses_child", "subagent", 1700000005000)
            os.utime(child_dir, (1, 1))  # Older than every pre-existing candidate.

        # Add after startup has recorded the baseline, before the timer refresh.
        original_poll = monitor._poll_live_switch_command
        first = True

        def poll_and_add():
            nonlocal first
            command = original_poll()
            if first:
                add_child()
                first = False
            return command

        monkeypatch.setattr(monitor, "_poll_live_switch_command", poll_and_add)
        monitor.start_monitoring(
            str(tmp_path), refresh_interval=0, interactive_switch=True, last=1
        )

        assert parsed == ["ses_child"]
        assert hydrated == [["ses_selected"], ["ses_selected", "ses_child"]]

    def test_completed_turn_counts_query_selected_sqlite_ids_only(self, monkeypatch):
        monitor = LiveMonitor(pricing_data={}, init_from_db=False)
        workflow = {"all_sessions": [SimpleNamespace(session_id="main"), SimpleNamespace(session_id="child")]}
        monkeypatch.setattr(SQLiteProcessor, "find_database_path", lambda: Path("/tmp/db"))
        count = patch.object(SQLiteProcessor, "get_completed_turn_counts", return_value={"agent": 3})

        with count as count_mock:
            assert monitor._get_completed_turn_counts(workflow, sqlite_mode=True) == {"agent": 3}
            assert monitor._get_completed_turn_counts(workflow, sqlite_mode=True) == {"agent": 3}
            assert monitor._get_completed_turn_counts(self._workflow("file"), sqlite_mode=False) is None

        count_mock.assert_called_once_with(["main", "child"], Path("/tmp/db"))

    def test_recent_turn_summary_uses_stored_prompt_metric_and_unavailable_label(self):
        monitor = LiveMonitor(pricing_data={}, init_from_db=False)

        available = monitor._completed_turn_summary({"build": 2}).plain
        unavailable = monitor._completed_turn_summary(None).plain

        assert "Completed stored prompts by agent:" in available
        assert "known synthetic excluded" in available
        assert "build: 2" in available
        assert "Completed stored prompts by agent:" in unavailable
        assert "Unavailable" in unavailable
        assert "known synthetic excluded" in unavailable

    def test_recent_turn_manual_refresh_updates_completed_count_summary(self, monkeypatch):
        monitor = LiveMonitor(pricing_data={}, init_from_db=False)
        monkeypatch.setattr("ocmonitor.services.live_monitor.sys.stdin.isatty", lambda: True)
        monkeypatch.setattr(monitor, "_describe_recent_turns", lambda *_a, **_k: [])
        commands = iter(["R", "q"])
        monkeypatch.setattr(monitor, "_poll_recent_turn_command", lambda: next(commands))
        refreshed_workflow = {"all_sessions": [SimpleNamespace(session_id="selected")]}
        monkeypatch.setattr(monitor, "_generate_workflow_dashboard", lambda *_a, **_k: "view")
        live = SimpleNamespace(update=lambda *_a, **_k: None)
        refresh = lambda: refreshed_workflow
        counts = iter([{"agent": 1}, {"agent": 2}])
        count_calls = []
        rendered_counts = []

        def resolve(workflow):
            count_calls.append(workflow)
            return next(counts)

        monkeypatch.setattr(
            monitor, "_completed_turn_summary",
            lambda summary: rendered_counts.append(summary) or "summary",
        )

        monitor._inspect_recent_turns_during_live(
            live,
            {"all_sessions": [SimpleNamespace(session_id="selected")]},
            "Recent Turns",
            False,
            refresh_workflow=refresh,
            refresh_interval=99,
            resolve_completed_turn_counts=resolve,
        )

        assert len(count_calls) == 2
        assert count_calls[1] is refreshed_workflow
        assert rendered_counts == [{"agent": 1}, {"agent": 2}]

    @pytest.mark.parametrize("refresh_mode", ["timer", "manual"])
    def test_recent_turn_disappeared_file_selection_clears_stale_data_and_can_quit(
        self, monkeypatch, tmp_path, refresh_mode
    ):
        monitor = LiveMonitor(pricing_data={}, init_from_db=False)
        monkeypatch.setattr("ocmonitor.services.live_monitor.sys.stdin.isatty", lambda: True)
        rendered_tables = []

        def build_table(descriptors, *_args, **_kwargs):
            rendered_tables.append(list(descriptors))
            return f"turns:{descriptors}"

        monkeypatch.setattr(monitor, "_build_recent_turn_picker_table", build_table)
        turn_commands = iter(([None, "q"] if refresh_mode == "timer" else ["R", "q"]))
        monkeypatch.setattr(monitor, "_poll_recent_turn_command", lambda: next(turn_commands))
        live_commands = iter(["t", "q"])
        monkeypatch.setattr(monitor, "_poll_live_switch_command", lambda: next(live_commands))
        monkeypatch.setattr(monitor, "_enable_raw_input_mode", lambda: True)
        monkeypatch.setattr(live_monitor_module, "Live", self._Live)
        selected = self._candidate("deleted-parent", 2)
        monkeypatch.setattr(monitor, "_get_file_workflow_metadata", lambda *_a, **_k: [selected])
        monkeypatch.setattr(monitor, "_hydrate_file_metadata_workflow", lambda _path, metadata: self._workflow(metadata.workflow_id))
        monkeypatch.setattr(FileProcessor, "refresh_session_metadata", lambda _path, cache, **_kwargs: SimpleNamespace(
            entries={}, dir_mtimes_ns={}, known_dir_ids=set()
        ))
        monkeypatch.setattr(monitor, "_describe_recent_turns", lambda *_a, **_k: [{"turn": "deleted-parent-turn"}])
        monkeypatch.setattr(monitor, "_generate_workflow_dashboard", lambda *_a, **_k: "view")
        updates = []
        monkeypatch.setattr(self._Live, "update", lambda self, renderable, **_kwargs: updates.append(renderable))

        monitor.start_monitoring(
            str(tmp_path), refresh_interval=0 if refresh_mode == "timer" else 99,
            interactive_switch=True,
        )

        assert rendered_tables[-1] == []
        assert updates[-1].renderables[0] == (
            "[status.error]Selected workflow is no longer available. "
            "Live monitoring will stop.[/status.error]"
        )
        assert "deleted-parent-turn" not in str(updates[-1].renderables)
        assert monitor._live_status_line == (
            "Selected workflow is no longer available. Live monitoring will stop."
        )
