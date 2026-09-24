from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from rich.text import Text
from ocmonitor.config import PathsConfig
from ocmonitor.services.live_monitor import LiveMonitor


class TestMultiWorkflowTracking:
    @staticmethod
    def _metadata(workflow_id, activity, **extra):
        return {
            "workflow_id": workflow_id,
            "main_session_id": workflow_id,
            "member_session_ids": [workflow_id],
            "last_activity_ts": activity,
            "active": True,
            **extra,
        }

    def test_tracks_multiple_active_workflows_from_metadata(self, monkeypatch, tmp_path):
        candidates = [self._metadata("session-a", 10), self._metadata("session-b", 20)]
        monkeypatch.setattr(
            "ocmonitor.services.live_monitor.SQLiteProcessor.find_database_path",
            lambda: str(tmp_path / "test.db"),
        )
        monkeypatch.setattr(
            "ocmonitor.services.live_monitor.SQLiteProcessor.list_active_workflow_metadata",
            lambda _: candidates,
        )
        monitor = LiveMonitor(
            pricing_data={}, paths_config=PathsConfig(messages_dir=str(tmp_path))
        )

        assert monitor._get_tracked_workflow_ids() == {"session-a", "session-b"}
        assert monitor._displayed_workflow_id == "session-b"
        assert monitor._get_displayed_workflow() is candidates[1]

    def test_initial_tracking_uses_only_active_metadata(self, monkeypatch, tmp_path):
        active = self._metadata("session-active", 20)
        monkeypatch.setattr(
            "ocmonitor.services.live_monitor.SQLiteProcessor.find_database_path",
            lambda: str(tmp_path / "test.db"),
        )
        monkeypatch.setattr(
            "ocmonitor.services.live_monitor.SQLiteProcessor.list_active_workflow_metadata",
            lambda _: [active],
        )
        monitor = LiveMonitor(
            pricing_data={}, paths_config=PathsConfig(messages_dir=str(tmp_path))
        )

        assert monitor._get_tracked_workflow_ids() == {"session-active"}
        assert "session-ended" not in monitor._get_tracked_workflow_ids()

    def test_displays_most_recently_active_metadata(self, monkeypatch, tmp_path):
        older = self._metadata("session-old", 100)
        newer = self._metadata("session-new", 200)
        monkeypatch.setattr(
            "ocmonitor.services.live_monitor.SQLiteProcessor.find_database_path",
            lambda: str(tmp_path / "test.db"),
        )
        monkeypatch.setattr(
            "ocmonitor.services.live_monitor.SQLiteProcessor.list_active_workflow_metadata",
            lambda _: [older, newer],
        )
        monitor = LiveMonitor(
            pricing_data={}, paths_config=PathsConfig(messages_dir=str(tmp_path))
        )

        assert monitor._get_displayed_workflow() is newer

    def test_selected_workflow_switch_resolves_from_metadata(self, monkeypatch, tmp_path):
        candidates = [self._metadata("workflow-a", 100), self._metadata("workflow-b", 200)]
        hydrated = {"workflow_id": "workflow-b", "all_sessions": []}
        monkeypatch.setattr(
            "ocmonitor.services.live_monitor.SQLiteProcessor.find_database_path",
            lambda: tmp_path / "test.db",
        )
        monkeypatch.setattr(
            "ocmonitor.services.live_monitor.SQLiteProcessor.list_active_workflow_metadata",
            lambda *_args, **_kwargs: candidates,
        )
        monkeypatch.setattr(
            "ocmonitor.services.live_monitor.SQLiteProcessor.load_workflow_from_metadata",
            lambda metadata, _db: {"workflow_id": metadata["workflow_id"], "all_sessions": []},
        )
        monitor = LiveMonitor(pricing_data={}, init_from_db=False)

        result = monitor._get_sqlite_active_workflows(selected_session_id="workflow-b")

        assert result == [hydrated]

    def test_selected_hydration_tracks_sub_agents(self, monkeypatch, tmp_path):
        candidate = self._metadata(
            "main-session", 200, member_session_ids=["main-session", "sub-agent-1"],
            session_count=2, sub_agent_count=1,
        )
        hydrated = {
            "workflow_id": "main-session",
            "all_sessions": [SimpleNamespace(session_id=sid) for sid in candidate["member_session_ids"]],
        }
        monkeypatch.setattr(
            "ocmonitor.services.live_monitor.SQLiteProcessor.find_database_path",
            lambda: tmp_path / "test.db",
        )
        monkeypatch.setattr(
            "ocmonitor.services.live_monitor.SQLiteProcessor.list_active_workflow_metadata",
            lambda *_args, **_kwargs: [candidate],
        )
        monkeypatch.setattr(
            "ocmonitor.services.live_monitor.SQLiteProcessor.load_workflow_from_metadata",
            lambda metadata, _db: hydrated,
        )
        monitor = LiveMonitor(pricing_data={}, init_from_db=False)

        workflows = monitor._get_sqlite_active_workflows(selected_session_id="main-session")

        assert workflows == [hydrated]
        assert {s.session_id for s in workflows[0]["all_sessions"]} == {
            "main-session", "sub-agent-1"
        }
        assert candidate["sub_agent_count"] == 1

    def test_metadata_switch_does_not_hydrate_other_workflow(self, monkeypatch, tmp_path):
        candidates = [
            self._metadata("workflow-a", 100),
            self._metadata("workflow-b", 200),
        ]
        hydrated_ids = []

        def hydrate(metadata, _db):
            hydrated_ids.append(metadata["workflow_id"])
            return {"workflow_id": metadata["workflow_id"], "all_sessions": []}

        monkeypatch.setattr(
            "ocmonitor.services.live_monitor.SQLiteProcessor.find_database_path",
            lambda: tmp_path / "test.db",
        )
        monkeypatch.setattr(
            "ocmonitor.services.live_monitor.SQLiteProcessor.list_active_workflow_metadata",
            lambda *_args, **_kwargs: candidates,
        )
        monkeypatch.setattr(
            "ocmonitor.services.live_monitor.SQLiteProcessor.load_workflow_from_metadata", hydrate
        )
        monitor = LiveMonitor(pricing_data={}, init_from_db=False)

        selected = monitor._get_sqlite_active_workflows(selected_session_id="workflow-a")

        assert [item["workflow_id"] for item in selected] == ["workflow-a"]
        assert hydrated_ids == ["workflow-a"]


class TestParentActivitySelection:
    @staticmethod
    def _candidate(workflow_id, activity, member_ids=None, **extra):
        return {
            "workflow_id": workflow_id,
            "main_session_id": (member_ids or [workflow_id])[0],
            "member_session_ids": member_ids or [workflow_id],
            "last_activity_ts": activity,
            "active": True,
            **extra,
        }

    def test_selection_uses_parent_activity_only_not_sub_agent(self, monkeypatch, tmp_path):
        # Metadata activity is derived from the parent, not the newer child activity.
        parent_a = self._candidate("workflow-a", 100, ["parent-a", "sub-agent-a"])
        parent_b = self._candidate("workflow-b", 150)
        monkeypatch.setattr(
            "ocmonitor.services.live_monitor.SQLiteProcessor.find_database_path",
            lambda: tmp_path / "test.db",
        )
        monkeypatch.setattr(
            "ocmonitor.services.live_monitor.SQLiteProcessor.list_active_workflow_metadata",
            lambda *_args, **_kwargs: [parent_a, parent_b],
        )
        monitor = LiveMonitor(pricing_data={}, init_from_db=True)

        assert monitor._displayed_workflow_id == "workflow-b"
        assert monitor._get_displayed_workflow() is parent_b

    def test_parent_appears_when_dispatching_sub_agent(self, monkeypatch, tmp_path):
        dispatching_parent = self._candidate(
            "workflow-a", 200, ["parent-a", "sub-agent-a"], sub_agent_count=1
        )
        other_parent = self._candidate("workflow-b", 150)
        monkeypatch.setattr(
            "ocmonitor.services.live_monitor.SQLiteProcessor.find_database_path",
            lambda: tmp_path / "test.db",
        )
        monkeypatch.setattr(
            "ocmonitor.services.live_monitor.SQLiteProcessor.list_active_workflow_metadata",
            lambda *_args, **_kwargs: [other_parent, dispatching_parent],
        )
        monitor = LiveMonitor(pricing_data={}, init_from_db=True)

        assert monitor._displayed_workflow_id == "workflow-a"
        assert monitor._get_displayed_workflow()["member_session_ids"] == [
            "parent-a", "sub-agent-a"
        ]

    def test_workflow_metadata_includes_all_sub_agents_regardless_of_activity(
        self, monkeypatch, tmp_path
    ):
        candidate = self._candidate(
            "workflow-with-subs", 200,
            ["parent", "sub-ended", "sub-active"], sub_agent_count=2,
        )
        monkeypatch.setattr(
            "ocmonitor.services.live_monitor.SQLiteProcessor.find_database_path",
            lambda: tmp_path / "test.db",
        )
        monkeypatch.setattr(
            "ocmonitor.services.live_monitor.SQLiteProcessor.list_active_workflow_metadata",
            lambda *_args, **_kwargs: [candidate],
        )
        monitor = LiveMonitor(pricing_data={}, init_from_db=True)

        displayed = monitor._get_displayed_workflow()

        assert displayed["member_session_ids"] == ["parent", "sub-ended", "sub-active"]
        assert displayed["sub_agent_count"] == 2


class TestOrphanSubAgentDetection:
    @staticmethod
    def _orphan(workflow_id, member_ids, activity=0):
        return {
            "workflow_id": workflow_id,
            "main_session_id": member_ids[0],
            "member_session_ids": member_ids,
            "last_activity_ts": activity,
            "active": True,
            "is_orphan": True,
        }

    def test_single_orphan_group_is_available_from_metadata(self, monkeypatch, tmp_path):
        orphan = self._orphan("missing-parent-id", ["orphan-sub-1", "orphan-sub-2"])
        monkeypatch.setattr(
            "ocmonitor.services.live_monitor.SQLiteProcessor.find_database_path",
            lambda: tmp_path / "test.db",
        )
        monkeypatch.setattr(
            "ocmonitor.services.live_monitor.SQLiteProcessor.list_active_workflow_metadata",
            lambda *_args, **_kwargs: [orphan],
        )
        monitor = LiveMonitor(pricing_data={}, init_from_db=True)

        assert monitor._displayed_workflow_id == "missing-parent-id"
        assert monitor._get_displayed_workflow()["is_orphan"] is True
        assert monitor._get_displayed_workflow()["member_session_ids"] == [
            "orphan-sub-1", "orphan-sub-2"
        ]

    def test_multiple_orphan_groups_remain_separate_metadata_workflows(
        self, monkeypatch, tmp_path
    ):
        orphan_a = self._orphan("parent-a", ["sub-a1", "sub-a2"], 100)
        orphan_b = self._orphan("parent-b", ["sub-b1"], 200)
        monkeypatch.setattr(
            "ocmonitor.services.live_monitor.SQLiteProcessor.find_database_path",
            lambda: tmp_path / "test.db",
        )
        monkeypatch.setattr(
            "ocmonitor.services.live_monitor.SQLiteProcessor.list_active_workflow_metadata",
            lambda *_args, **_kwargs: [orphan_a, orphan_b],
        )
        monitor = LiveMonitor(pricing_data={}, init_from_db=True)

        assert monitor._get_tracked_workflow_ids() == {"parent-a", "parent-b"}
        assert monitor._displayed_workflow_id == "parent-b"

    def test_normal_and_orphan_workflows_both_remain_tracked(self, monkeypatch, tmp_path):
        normal = {
            **self._orphan("normal-parent", ["normal-parent", "normal-sub"], 200),
            "is_orphan": False,
        }
        orphan = self._orphan("orphan-parent", ["orphan-sub"], 100)
        monkeypatch.setattr(
            "ocmonitor.services.live_monitor.SQLiteProcessor.find_database_path",
            lambda: tmp_path / "test.db",
        )
        monkeypatch.setattr(
            "ocmonitor.services.live_monitor.SQLiteProcessor.list_active_workflow_metadata",
            lambda *_args, **_kwargs: [normal, orphan],
        )
        monitor = LiveMonitor(pricing_data={}, init_from_db=True)

        assert monitor._get_tracked_workflow_ids() == {"normal-parent", "orphan-parent"}


class TestLiveMonitorValidation:
    def test_validate_monitoring_setup_uses_default_file_storage_when_path_not_provided(
        self, monkeypatch, tmp_path
    ):
        sessions_dir = tmp_path / "message"
        sessions_dir.mkdir()

        paths_config = PathsConfig(messages_dir=str(sessions_dir))
        monitor = LiveMonitor(pricing_data={}, paths_config=paths_config)

        monkeypatch.setattr(
            "ocmonitor.services.live_monitor.SQLiteProcessor.find_database_path",
            lambda: None,
        )
        monkeypatch.setattr(
            "ocmonitor.services.live_monitor.FileProcessor.find_session_directories",
            lambda _: [tmp_path / "session-1"],
        )

        result = monitor.validate_monitoring_setup()

        assert result["valid"] is True
        assert result["info"]["sqlite"]["available"] is False
        assert result["info"]["files"]["available"] is True
        assert result["info"]["files"]["path"] == str(sessions_dir)

    def test_validate_monitoring_setup_fails_when_default_file_storage_missing(
        self, monkeypatch, tmp_path
    ):
        missing_dir = tmp_path / "missing"

        paths_config = PathsConfig(messages_dir=str(missing_dir))
        monitor = LiveMonitor(pricing_data={}, paths_config=paths_config)

        monkeypatch.setattr(
            "ocmonitor.services.live_monitor.SQLiteProcessor.find_database_path",
            lambda: None,
        )

        result = monitor.validate_monitoring_setup()

        assert result["valid"] is False
        assert (
            "No session data source found. Expected SQLite database or file storage."
            in result["issues"]
        )

    def test_validate_monitoring_setup_uses_explicit_base_path(
        self, monkeypatch, tmp_path
    ):
        explicit_path = tmp_path / "explicit-message"
        explicit_path.mkdir()

        paths_config = PathsConfig(messages_dir=str(tmp_path / "default-message"))
        monitor = LiveMonitor(pricing_data={}, paths_config=paths_config)

        monkeypatch.setattr(
            "ocmonitor.services.live_monitor.SQLiteProcessor.find_database_path",
            lambda: None,
        )
        monkeypatch.setattr(
            "ocmonitor.services.live_monitor.FileProcessor.find_session_directories",
            lambda _: [tmp_path / "session-1"],
        )

        result = monitor.validate_monitoring_setup(str(explicit_path))

        assert result["valid"] is True
        assert result["info"]["files"]["path"] == str(explicit_path)

    def test_validate_monitoring_setup_no_paths_config_and_no_base_path(
        self, monkeypatch
    ):
        monitor = LiveMonitor(pricing_data={})

        monkeypatch.setattr(
            "ocmonitor.services.live_monitor.SQLiteProcessor.find_database_path",
            lambda: None,
        )

        result = monitor.validate_monitoring_setup()

        assert result["valid"] is False
        assert result["info"]["files"]["available"] is False


class TestLiveMonitorToolStatsSourceSelection:
    """Tests for tool stats source selection in live monitor."""

    def test_file_mode_tool_loading_does_not_fallback_to_sqlite(
        self, monkeypatch, tmp_path
    ):
        """Verify file-mode workflow doesn't pull SQLite tool stats even if SQLite is available."""
        sessions_dir = tmp_path / "message"
        sessions_dir.mkdir()

        paths_config = PathsConfig(messages_dir=str(sessions_dir))
        monitor = LiveMonitor(pricing_data={}, paths_config=paths_config)

        # Mock SQLite as available
        db_path = tmp_path / "opencode.db"
        db_path.touch()
        monkeypatch.setattr(
            "ocmonitor.services.live_monitor.SQLiteProcessor.find_database_path",
            lambda: db_path,
        )

        # Mock file processor to return sessions
        monkeypatch.setattr(
            "ocmonitor.services.live_monitor.FileProcessor.find_session_directories",
            lambda _: [tmp_path / "session-1"],
        )

        # Create a mock workflow with session IDs
        from unittest.mock import MagicMock

        mock_workflow = MagicMock()
        mock_workflow.all_sessions = [MagicMock(session_id="ses_file_1")]

        # Call with preferred_source="files"
        tool_stats = monitor._load_tool_stats_for_workflow(
            mock_workflow, preferred_source="files"
        )

        # Should return empty list for file mode, not SQLite data
        assert tool_stats == []

    def test_sqlite_mode_tool_loading_uses_sqlite(self, monkeypatch, tmp_path):
        """Verify SQLite-mode workflow queries SQLite for tool stats."""
        monitor = LiveMonitor(pricing_data={})

        # Mock SQLite as available
        db_path = tmp_path / "opencode.db"
        db_path.touch()
        monkeypatch.setattr(
            "ocmonitor.services.live_monitor.SQLiteProcessor.find_database_path",
            lambda: db_path,
        )

        # Mock the SQLite processor method to track calls
        from unittest.mock import MagicMock, patch

        mock_stats = [MagicMock(tool_name="bash", total_calls=5)]
        with patch(
            "ocmonitor.services.live_monitor.SQLiteProcessor.load_tool_usage_for_sessions",
            return_value=mock_stats,
        ) as mock_load:
            # Create a mock workflow with session IDs
            mock_workflow = MagicMock()
            mock_workflow.all_sessions = [MagicMock(session_id="ses_sqlite_1")]

            # Call with preferred_source="sqlite"
            tool_stats = monitor._load_tool_stats_for_workflow(
                mock_workflow, preferred_source="sqlite"
            )

            # Should have called SQLite processor
            mock_load.assert_called_once()
            assert tool_stats == mock_stats


class TestLiveMonitorSelection:
    def test_resolve_selected_sqlite_workflow_by_sub_agent_id(self):
        monitor = LiveMonitor(pricing_data={}, init_from_db=False)

        workflow_a = {
            "workflow_id": "workflow-a",
            "main_session": MagicMock(session_id="main-a"),
            "all_sessions": [
                MagicMock(session_id="main-a"),
                MagicMock(session_id="sub-a1"),
            ],
            "display_title": "Workflow A",
            "project_name": "proj-a",
            "session_count": 2,
            "sub_agent_count": 1,
        }
        workflow_b = {
            "workflow_id": "workflow-b",
            "main_session": MagicMock(session_id="main-b"),
            "all_sessions": [MagicMock(session_id="main-b")],
            "display_title": "Workflow B",
            "project_name": "proj-b",
            "session_count": 1,
            "sub_agent_count": 0,
        }

        resolved = monitor._resolve_selected_sqlite_workflow(
            [workflow_a, workflow_b], "sub-a1"
        )

        assert resolved is workflow_a

    def test_resolve_selected_file_workflow_by_sub_agent_id(self):
        monitor = LiveMonitor(pricing_data={}, init_from_db=False)

        workflow_a = SimpleNamespace(
            workflow_id="workflow-a",
            main_session=SimpleNamespace(session_id="main-a"),
            all_sessions=[
                SimpleNamespace(session_id="main-a"),
                SimpleNamespace(session_id="sub-a1"),
            ],
        )
        workflow_b = SimpleNamespace(
            workflow_id="workflow-b",
            main_session=SimpleNamespace(session_id="main-b"),
            all_sessions=[SimpleNamespace(session_id="main-b")],
        )

        resolved = monitor._resolve_selected_file_workflow(
            [workflow_a, workflow_b], "sub-a1"
        )

        assert resolved is workflow_a

    def test_handle_live_switch_command_next_previous_and_number(self):
        monitor = LiveMonitor(pricing_data={}, init_from_db=False)

        descriptors = [
            {"workflow_id": "wf-1"},
            {"workflow_id": "wf-2"},
            {"workflow_id": "wf-3"},
        ]

        new_id, should_quit = monitor._handle_live_switch_command(
            "n", descriptors, "wf-1"
        )
        assert should_quit is False
        assert new_id == "wf-2"

        new_id, should_quit = monitor._handle_live_switch_command(
            "p", descriptors, "wf-2"
        )
        assert should_quit is False
        assert new_id == "wf-1"

        new_id, should_quit = monitor._handle_live_switch_command(
            "3", descriptors, "wf-1"
        )
        assert should_quit is False
        assert new_id == "wf-3"

    def test_file_loader_disables_fallback_in_pinned_mode(self, monkeypatch, tmp_path):
        monitor = LiveMonitor(pricing_data={}, init_from_db=False)

        ended_workflow = SimpleNamespace(workflow_id="wf-ended", end_time=1)
        monkeypatch.setattr(
            "ocmonitor.services.live_monitor.FileProcessor.load_all_sessions",
            lambda base_path, limit=50: [SimpleNamespace(session_id="ses_1")],
        )
        monkeypatch.setattr(
            monitor.session_grouper,
            "group_sessions",
            lambda sessions: [ended_workflow],
        )

        result = monitor._get_file_active_workflows(str(tmp_path), allow_fallback=False)
        assert result == []

    def test_file_loader_falls_back_to_recent_metadata_and_hydrates_one(
        self, monkeypatch, tmp_path
    ):
        monitor = LiveMonitor(pricing_data={}, init_from_db=False)
        metadata = [
            SimpleNamespace(
                workflow_id=f"wf-{i}",
                all_sessions=[SimpleNamespace(session_id=f"wf-{i}")],
                end_time=1,
                last_activity_ts=10 - i,
            )
            for i in range(10)
        ]
        monkeypatch.setattr(monitor, "_get_file_workflow_metadata", lambda *_a, **_k: metadata[:5])
        hydrated = []

        def hydrate(_base_path, selected):
            hydrated.append(selected.workflow_id)
            return SimpleNamespace(workflow_id=selected.workflow_id)

        monkeypatch.setattr(monitor, "_hydrate_file_metadata_workflow", hydrate)

        result = monitor._get_file_active_workflows(str(tmp_path), allow_fallback=True)

        assert [workflow.workflow_id for workflow in result] == ["wf-0"]
        assert hydrated == ["wf-0"]

    def test_sqlite_loader_disables_fallback_in_pinned_mode(
        self, monkeypatch, tmp_path
    ):
        monitor = LiveMonitor(pricing_data={}, init_from_db=False)
        db_path = tmp_path / "opencode.db"
        db_path.touch()
        active = {"workflow_id": "wf-active", "active": True, "member_session_ids": ["wf-active"]}
        monkeypatch.setattr(
            "ocmonitor.services.live_monitor.SQLiteProcessor.find_database_path",
            lambda: db_path,
        )
        monkeypatch.setattr(
            "ocmonitor.services.live_monitor.SQLiteProcessor.list_active_workflow_metadata",
            lambda *_args, **_kwargs: [active],
        )
        recent = MagicMock(return_value=[{"workflow_id": "wf-ended"}])
        monkeypatch.setattr(
            "ocmonitor.services.live_monitor.SQLiteProcessor.list_recent_workflow_metadata",
            recent,
        )
        hydrated = MagicMock(return_value={"workflow_id": "wf-active"})
        monkeypatch.setattr(
            "ocmonitor.services.live_monitor.SQLiteProcessor.load_workflow_from_metadata",
            hydrated,
        )

        result = monitor._get_sqlite_active_workflows(allow_fallback=False)

        assert result == [{"workflow_id": "wf-active"}]
        recent.assert_not_called()
        hydrated.assert_called_once_with(active, db_path)

    def test_sqlite_loader_falls_back_to_recent_metadata_and_hydrates_one(
        self, monkeypatch, tmp_path
    ):
        monitor = LiveMonitor(pricing_data={}, init_from_db=False)
        db_path = tmp_path / "opencode.db"
        db_path.touch()
        recent = [
            {
                "workflow_id": f"wf-{i}",
                "active": False,
                "member_session_ids": [f"wf-{i}"],
                "last_activity_ts": 10 - i,
            }
            for i in range(5)
        ]
        monkeypatch.setattr(
            "ocmonitor.services.live_monitor.SQLiteProcessor.find_database_path",
            lambda: db_path,
        )
        monkeypatch.setattr(
            "ocmonitor.services.live_monitor.SQLiteProcessor.list_active_workflow_metadata",
            lambda *_args, **_kwargs: [],
        )
        monkeypatch.setattr(
            "ocmonitor.services.live_monitor.SQLiteProcessor.list_recent_workflow_metadata",
            lambda _db, limit=5: recent[:limit],
        )
        hydrated = []

        def hydrate(metadata, _db):
            hydrated.append(metadata["workflow_id"])
            return {"workflow_id": metadata["workflow_id"]}

        monkeypatch.setattr(
            "ocmonitor.services.live_monitor.SQLiteProcessor.load_workflow_from_metadata",
            hydrate,
        )

        result = monitor._get_sqlite_active_workflows(allow_fallback=True)

        assert [workflow["workflow_id"] for workflow in result] == ["wf-0"]
        assert hydrated == ["wf-0"]

    def test_handle_live_switch_command_show_does_not_switch(self):
        monitor = LiveMonitor(pricing_data={}, init_from_db=False)
        monitor._print_workflow_picker_table = MagicMock()

        new_id, should_quit = monitor._handle_live_switch_command(
            "s", [{"workflow_id": "wf-1"}], "wf-1"
        )

        assert should_quit is False
        assert new_id is None
        monitor._print_workflow_picker_table.assert_called_once()

    def test_handle_live_switch_command_invalid_number_does_not_switch(self):
        monitor = LiveMonitor(pricing_data={}, init_from_db=False)
        monitor.console.print = MagicMock()

        new_id, should_quit = monitor._handle_live_switch_command(
            "9", [{"workflow_id": "wf-1"}], "wf-1"
        )

        assert should_quit is False
        assert new_id is None
        monitor.console.print.assert_called()

    def test_handle_live_switch_command_unknown_does_not_switch(self):
        monitor = LiveMonitor(pricing_data={}, init_from_db=False)
        monitor.console.print = MagicMock()

        new_id, should_quit = monitor._handle_live_switch_command(
            "x", [{"workflow_id": "wf-1"}], "wf-1"
        )

        assert should_quit is False
        assert new_id is None
        monitor.console.print.assert_called()

    def test_apply_switch_command_selection_only_switches_on_new_id(self):
        monitor = LiveMonitor(pricing_data={}, init_from_db=False)

        selected, switched = monitor._apply_switch_command_selection(None, "wf-1", None)
        assert switched is False
        assert selected is None

        selected, switched = monitor._apply_switch_command_selection(
            None, "wf-1", "wf-1"
        )
        assert switched is False
        assert selected is None

        selected, switched = monitor._apply_switch_command_selection(
            None, "wf-1", "wf-2"
        )
        assert switched is True
        assert selected == "wf-2"

    def test_prompt_for_workflow_selection_accepts_number(self, monkeypatch):
        monitor = LiveMonitor(pricing_data={}, init_from_db=False)
        monkeypatch.setattr(
            monitor, "_print_workflow_picker_table", lambda descriptors, title: None
        )
        monkeypatch.setattr(monitor.console, "input", lambda _: "2")

        selected = monitor._prompt_for_workflow_selection(
            [
                {"workflow_id": "wf-1"},
                {"workflow_id": "wf-2"},
            ],
            "Select Workflow",
        )

        assert selected == "wf-2"


class TestLiveMonitorToolStatsByModelSourceSelection:
    def test_file_mode_tool_by_model_returns_empty(self, monkeypatch, tmp_path):
        """Verify file-mode workflow returns empty for tool by model loading."""
        sessions_dir = tmp_path / "message"
        sessions_dir.mkdir()

        paths_config = PathsConfig(messages_dir=str(sessions_dir))
        monitor = LiveMonitor(pricing_data={}, paths_config=paths_config)

        db_path = tmp_path / "opencode.db"
        db_path.touch()
        monkeypatch.setattr(
            "ocmonitor.services.live_monitor.SQLiteProcessor.find_database_path",
            lambda: db_path,
        )

        from unittest.mock import MagicMock

        mock_workflow = MagicMock()
        mock_workflow.all_sessions = [MagicMock(session_id="ses_file_1")]

        tool_stats = monitor._load_tool_stats_by_model_for_workflow(
            mock_workflow, preferred_source="files"
        )

        assert tool_stats == []

    def test_sqlite_mode_tool_by_model_calls_sqlite(self, monkeypatch, tmp_path):
        """Verify SQLite-mode workflow queries SQLite for tool by model stats."""
        monitor = LiveMonitor(pricing_data={})

        db_path = tmp_path / "opencode.db"
        db_path.touch()
        monkeypatch.setattr(
            "ocmonitor.services.live_monitor.SQLiteProcessor.find_database_path",
            lambda: db_path,
        )

        from unittest.mock import MagicMock, patch

        mock_stats = [MagicMock(model_name="claude-3-5-sonnet", tool_stats=[])]
        with patch(
            "ocmonitor.services.live_monitor.SQLiteProcessor.load_tool_usage_by_model_for_sessions",
            return_value=mock_stats,
        ) as mock_load:
            mock_workflow = MagicMock()
            mock_workflow.all_sessions = [MagicMock(session_id="ses_sqlite_1")]

            tool_stats = monitor._load_tool_stats_by_model_for_workflow(
                mock_workflow, preferred_source="sqlite"
            )

            mock_load.assert_called_once()
            assert tool_stats == mock_stats


class TestExecuteWorkflowSwitch:
    """Tests for the _execute_workflow_switch refactored method."""

    def test_execute_workflow_switch_no_switch_when_no_new_id(self, tmp_path):
        """Should return unchanged state when new_id is None."""
        from ocmonitor.services.live_monitor import LiveMonitor
        from ocmonitor.config import PathsConfig

        paths_config = PathsConfig(messages_dir=str(tmp_path))
        monitor = LiveMonitor(pricing_data={}, paths_config=paths_config)
        monitor.prev_tracked = set()

        mock_workflow = MagicMock()
        mock_workflow.workflow_id = "wf-1"
        mock_workflow.all_sessions = [MagicMock(session_id="ses-1")]

        result_id, result_workflow, result_selected = monitor._execute_workflow_switch(
            new_id=None,
            selected_session_id=None,
            current_workflow_id="wf-1",
            current_workflow=mock_workflow,
            active_workflows=[mock_workflow],
            live=MagicMock(),
            descriptors=[],
            interactive_switch=False,
            refresh_interval=5,
        )

        assert result_id == "wf-1"
        assert result_workflow == mock_workflow
        assert result_selected is None
        assert monitor.prev_tracked == set()

    def test_execute_workflow_switch_no_switch_when_same_id(self, tmp_path):
        """Should return unchanged state when new_id matches current."""
        from ocmonitor.services.live_monitor import LiveMonitor
        from ocmonitor.config import PathsConfig

        paths_config = PathsConfig(messages_dir=str(tmp_path))
        monitor = LiveMonitor(pricing_data={}, paths_config=paths_config)

        mock_workflow = MagicMock()
        mock_workflow.workflow_id = "wf-1"
        mock_workflow.all_sessions = [MagicMock(session_id="ses-1")]

        result_id, result_workflow, result_selected = monitor._execute_workflow_switch(
            new_id="wf-1",
            selected_session_id=None,
            current_workflow_id="wf-1",
            current_workflow=mock_workflow,
            active_workflows=[mock_workflow],
            live=MagicMock(),
            descriptors=[],
            interactive_switch=False,
            refresh_interval=5,
        )

        assert result_id == "wf-1"
        assert result_selected is None

    def test_execute_workflow_switch_switches_to_new_workflow(self, tmp_path):
        """Should update state and dashboard when switching to new workflow."""
        from ocmonitor.services.live_monitor import LiveMonitor
        from ocmonitor.config import PathsConfig

        paths_config = PathsConfig(messages_dir=str(tmp_path))
        monitor = LiveMonitor(pricing_data={}, paths_config=paths_config)
        monitor.prev_tracked = {"old-session"}
        monitor._generate_workflow_dashboard = MagicMock(return_value="mock_dashboard")

        workflow_1 = MagicMock()
        workflow_1.workflow_id = "wf-1"
        workflow_1.all_sessions = [MagicMock(session_id="ses-1")]

        workflow_2 = MagicMock()
        workflow_2.workflow_id = "wf-2"
        workflow_2.all_sessions = [
            MagicMock(session_id="ses-2"),
            MagicMock(session_id="ses-2b"),
        ]

        live_mock = MagicMock()

        result_id, result_workflow, result_selected = monitor._execute_workflow_switch(
            new_id="wf-2",
            selected_session_id=None,
            current_workflow_id="wf-1",
            current_workflow=workflow_1,
            active_workflows=[workflow_1, workflow_2],
            live=live_mock,
            descriptors=[],
            interactive_switch=False,
            refresh_interval=5,
        )

        assert result_id == "wf-2"
        assert result_workflow == workflow_2
        assert result_selected == "wf-2"
        assert monitor.prev_tracked == {"ses-2", "ses-2b"}
        assert monitor._live_status_line is not None
        assert "Switched to workflow wf-2" in monitor._live_status_line
        live_mock.update.assert_called_once()


class TestHandleListCommand:
    """Tests for the _handle_list_command refactored method."""

    def test_handle_list_command_returns_unchanged_when_no_picker_selection(
        self, tmp_path
    ):
        """Should return unchanged state when picker returns None."""
        from ocmonitor.services.live_monitor import LiveMonitor
        from ocmonitor.config import PathsConfig

        paths_config = PathsConfig(messages_dir=str(tmp_path))
        monitor = LiveMonitor(pricing_data={}, paths_config=paths_config)
        monitor._pick_workflow_during_live = MagicMock(return_value=None)

        mock_workflow = MagicMock()
        mock_workflow.workflow_id = "wf-1"

        result_id, result_workflow, result_selected = monitor._handle_list_command(
            live=MagicMock(),
            descriptors=[{"workflow_id": "wf-1"}],
            selected_session_id="wf-1",
            current_workflow_id="wf-1",
            current_workflow=mock_workflow,
            active_workflows=[mock_workflow],
            interactive_switch=True,
            refresh_interval=5,
        )

        assert result_id == "wf-1"
        assert result_workflow == mock_workflow
        assert result_selected == "wf-1"

    def test_handle_list_command_switches_when_picker_selects(self, tmp_path):
        """Should switch workflow when picker returns a selection."""
        from ocmonitor.services.live_monitor import LiveMonitor
        from ocmonitor.config import PathsConfig

        paths_config = PathsConfig(messages_dir=str(tmp_path))
        monitor = LiveMonitor(pricing_data={}, paths_config=paths_config)

        workflow_1 = MagicMock()
        workflow_1.workflow_id = "wf-1"
        workflow_1.all_sessions = [MagicMock(session_id="ses-1")]

        workflow_2 = MagicMock()
        workflow_2.workflow_id = "wf-2"
        workflow_2.all_sessions = [MagicMock(session_id="ses-2")]

        monitor._pick_workflow_during_live = MagicMock(return_value="wf-2")
        monitor._resolve_selected_file_workflow = MagicMock(return_value=workflow_2)
        monitor._generate_workflow_dashboard = MagicMock(return_value="mock_dashboard")

        live_mock = MagicMock()

        result_id, result_workflow, result_selected = monitor._handle_list_command(
            live=live_mock,
            descriptors=[{"workflow_id": "wf-1"}, {"workflow_id": "wf-2"}],
            selected_session_id="wf-1",
            current_workflow_id="wf-1",
            current_workflow=workflow_1,
            active_workflows=[workflow_1, workflow_2],
            interactive_switch=True,
            refresh_interval=5,
        )

        assert result_id == "wf-2"
        assert result_workflow == workflow_2
        assert result_selected == "wf-2"
        monitor._pick_workflow_during_live.assert_called_once()


class TestHandleNavigationCommand:
    """Tests for the _handle_navigation_command refactored method."""

    def test_handle_navigation_quit_command(self, tmp_path):
        """Should return should_quit=True when quit command received."""
        from ocmonitor.services.live_monitor import LiveMonitor
        from ocmonitor.config import PathsConfig

        paths_config = PathsConfig(messages_dir=str(tmp_path))
        monitor = LiveMonitor(pricing_data={}, paths_config=paths_config)

        mock_workflow = MagicMock()
        mock_workflow.workflow_id = "wf-1"

        should_quit, workflow_id, workflow, selected = (
            monitor._handle_navigation_command(
                command="q",
                descriptors=[{"workflow_id": "wf-1"}],
                selected_session_id="wf-1",
                current_workflow_id="wf-1",
                current_workflow=mock_workflow,
                active_workflows=[mock_workflow],
                live=MagicMock(),
                interactive_switch=True,
                refresh_interval=5,
            )
        )

        assert should_quit is True
        assert workflow_id == "wf-1"
        assert workflow == mock_workflow
        assert selected == "wf-1"

    def test_handle_navigation_next_command_switches_workflow(self, tmp_path):
        """Should switch to next workflow on 'n' command."""
        from ocmonitor.services.live_monitor import LiveMonitor
        from ocmonitor.config import PathsConfig

        paths_config = PathsConfig(messages_dir=str(tmp_path))
        monitor = LiveMonitor(pricing_data={}, paths_config=paths_config)

        workflow_1 = MagicMock()
        workflow_1.workflow_id = "wf-1"
        workflow_1.all_sessions = [MagicMock(session_id="ses-1")]

        workflow_2 = MagicMock()
        workflow_2.workflow_id = "wf-2"
        workflow_2.all_sessions = [MagicMock(session_id="ses-2")]

        monitor._resolve_selected_file_workflow = MagicMock(return_value=workflow_2)
        monitor._generate_workflow_dashboard = MagicMock(return_value="mock_dashboard")

        live_mock = MagicMock()

        should_quit, workflow_id, workflow, selected = (
            monitor._handle_navigation_command(
                command="n",
                descriptors=[{"workflow_id": "wf-1"}, {"workflow_id": "wf-2"}],
                selected_session_id=None,
                current_workflow_id="wf-1",
                current_workflow=workflow_1,
                active_workflows=[workflow_1, workflow_2],
                live=live_mock,
                interactive_switch=True,
                refresh_interval=5,
            )
        )

        assert should_quit is False
        assert workflow_id == "wf-2"
        assert workflow == workflow_2
        assert selected == "wf-2"
        live_mock.update.assert_called_once()

    def test_handle_navigation_prev_command_switches_workflow(self, tmp_path):
        """Should switch to previous workflow on 'p' command."""
        from ocmonitor.services.live_monitor import LiveMonitor
        from ocmonitor.config import PathsConfig

        paths_config = PathsConfig(messages_dir=str(tmp_path))
        monitor = LiveMonitor(pricing_data={}, paths_config=paths_config)

        workflow_1 = MagicMock()
        workflow_1.workflow_id = "wf-1"
        workflow_1.all_sessions = [MagicMock(session_id="ses-1")]

        workflow_2 = MagicMock()
        workflow_2.workflow_id = "wf-2"
        workflow_2.all_sessions = [MagicMock(session_id="ses-2")]

        monitor._resolve_selected_file_workflow = MagicMock(return_value=workflow_1)
        monitor._generate_workflow_dashboard = MagicMock(return_value="mock_dashboard")

        live_mock = MagicMock()

        should_quit, workflow_id, workflow, selected = (
            monitor._handle_navigation_command(
                command="p",
                descriptors=[{"workflow_id": "wf-1"}, {"workflow_id": "wf-2"}],
                selected_session_id=None,
                current_workflow_id="wf-2",
                current_workflow=workflow_2,
                active_workflows=[workflow_1, workflow_2],
                live=live_mock,
                interactive_switch=True,
                refresh_interval=5,
            )
        )

        assert should_quit is False
        assert workflow_id == "wf-1"
        assert workflow == workflow_1
        assert selected == "wf-1"

    def test_handle_navigation_number_command_jumps_to_workflow(self, tmp_path):
        """Should jump to specific workflow on number command."""
        from ocmonitor.services.live_monitor import LiveMonitor
        from ocmonitor.config import PathsConfig

        paths_config = PathsConfig(messages_dir=str(tmp_path))
        monitor = LiveMonitor(pricing_data={}, paths_config=paths_config)

        workflow_1 = MagicMock()
        workflow_1.workflow_id = "wf-1"
        workflow_1.all_sessions = [MagicMock(session_id="ses-1")]

        workflow_2 = MagicMock()
        workflow_2.workflow_id = "wf-2"
        workflow_2.all_sessions = [MagicMock(session_id="ses-2")]

        workflow_3 = MagicMock()
        workflow_3.workflow_id = "wf-3"
        workflow_3.all_sessions = [MagicMock(session_id="ses-3")]

        monitor._resolve_selected_file_workflow = MagicMock(return_value=workflow_3)
        monitor._generate_workflow_dashboard = MagicMock(return_value="mock_dashboard")

        live_mock = MagicMock()

        should_quit, workflow_id, workflow, selected = (
            monitor._handle_navigation_command(
                command="3",
                descriptors=[
                    {"workflow_id": "wf-1"},
                    {"workflow_id": "wf-2"},
                    {"workflow_id": "wf-3"},
                ],
                selected_session_id=None,
                current_workflow_id="wf-1",
                current_workflow=workflow_1,
                active_workflows=[workflow_1, workflow_2, workflow_3],
                live=live_mock,
                interactive_switch=True,
                refresh_interval=5,
            )
        )

        assert should_quit is False
        assert workflow_id == "wf-3"
        assert workflow == workflow_3
        assert selected == "wf-3"


class TestLiveMonitorProviderAwareRegressions:
    """Regression tests for provider-aware pricing lookups in live monitor."""

    def test_session_context_usage_uses_provider_aware_context_window(self, tmp_path):
        """Provider/model pricing should be used instead of default context window."""
        from decimal import Decimal
        from ocmonitor.config import ModelPricing
        from ocmonitor.models.session import InteractionFile, SessionData, TokenUsage

        pricing_data = {
            "github-copilot/claude-sonnet-4.5": ModelPricing(
                input=Decimal("1.0"),
                output=Decimal("2.0"),
                cacheWrite=Decimal("0.0"),
                cacheRead=Decimal("0.0"),
                contextWindow=100000,
                sessionQuota=Decimal("5.0"),
            )
        }

        monitor = LiveMonitor(
            pricing_data=pricing_data,
            paths_config=PathsConfig(messages_dir=str(tmp_path)),
        )

        inter_file = tmp_path / "inter_0001.json"
        inter_file.write_text("{}")
        interaction = InteractionFile(
            file_path=inter_file,
            session_id="ses_test",
            model_id="claude-sonnet-4.5",
            provider_id="github-copilot",
            tokens=TokenUsage(input=1000, output=100, cache_read=200, cache_write=300),
            raw_data={},
        )
        session = SessionData(
            session_id="ses_test",
            session_path=tmp_path / "ses_test",
            files=[interaction],
        )

        result = monitor._get_session_context_usage(session)

        assert "claude-sonnet-4.5" in result
        assert result["claude-sonnet-4.5"]["context_window"] == 100000


class TestRecentTurnInspection:
    """Tests for live-monitor recent-turn history inspection."""

    def _make_turn(self, tmp_path, session_id, name, created, total_output=100, agent="build"):
        from ocmonitor.models.session import InteractionFile, TimeData, TokenUsage

        path = tmp_path / name
        path.write_text("{}")
        return InteractionFile(
            file_path=path,
            session_id=session_id,
            model_id="claude-sonnet-4.5",
            provider_id="github-copilot",
            tokens=TokenUsage(
                input=1000,
                output=total_output,
                cache_read=200,
                cache_write=50,
            ),
            time_data=TimeData(created=created, completed=created + 2000),
            project_path=str(tmp_path),
            agent=agent,
            finish_reason="stop",
            raw_data={
                "role": "assistant",
                "content": [
                    {"type": "text", "text": f"Assistant summary for {name}"},
                    {
                        "type": "tool",
                        "tool": "bash",
                        "state": {"status": "completed", "input": "pytest -q"},
                    },
                ],
                "user": f"User request for {name}",
            },
        )

    def test_describe_recent_turns_orders_by_activity_and_limits(self, tmp_path):
        from ocmonitor.models.session import SessionData

        monitor = LiveMonitor(pricing_data={}, init_from_db=False)
        older = self._make_turn(tmp_path, "ses-1", "older.json", 1_000)
        newer = self._make_turn(tmp_path, "ses-1", "newer.json", 3_000)
        newest = self._make_turn(tmp_path, "ses-2", "newest.json", 5_000)
        workflow = SimpleNamespace(
            all_sessions=[
                SessionData(session_id="ses-1", files=[older, newer]),
                SessionData(session_id="ses-2", files=[newest]),
            ]
        )

        descriptors = monitor._describe_recent_turns(workflow, limit=2)

        assert [d["turn"].file_name for d in descriptors] == [
            "newest.json",
            "newer.json",
        ]
        assert descriptors[0]["tokens_total"] == newest.tokens.total

    def test_prompt_for_recent_turn_selection_accepts_number(self, tmp_path):
        from ocmonitor.models.session import SessionData

        monitor = LiveMonitor(pricing_data={}, init_from_db=False)
        turn = self._make_turn(tmp_path, "ses-1", "turn.json", 1_000)
        workflow = SimpleNamespace(
            all_sessions=[SessionData(session_id="ses-1", files=[turn])]
        )
        monitor._print_recent_turn_picker_table = MagicMock()
        monitor.console.input = MagicMock(return_value="1")

        selected = monitor._prompt_for_recent_turn_selection(workflow, "Recent Turns")

        assert selected is turn

    def test_prompt_for_recent_turn_selection_paginates(self, tmp_path):
        from ocmonitor.models.session import SessionData

        monitor = LiveMonitor(pricing_data={}, init_from_db=False)
        turns = [
            self._make_turn(tmp_path, "ses-1", f"turn-{idx}.json", idx * 1000)
            for idx in range(52)
        ]
        workflow = SimpleNamespace(
            all_sessions=[SessionData(session_id="ses-1", files=turns)]
        )
        monitor._print_recent_turn_picker_table = MagicMock()
        monitor.console.input = MagicMock(side_effect=["n", "51"])

        selected = monitor._prompt_for_recent_turn_selection(workflow, "Recent Turns")

        assert selected is turns[1]
        assert monitor._print_recent_turn_picker_table.call_args_list[0].args[2] == 0
        assert monitor._print_recent_turn_picker_table.call_args_list[1].args[2] == 1

    def test_prompt_for_recent_turn_selection_refreshes_turns(self, tmp_path):
        from ocmonitor.models.session import SessionData

        monitor = LiveMonitor(pricing_data={}, init_from_db=False)
        old_turn = self._make_turn(tmp_path, "ses-1", "old.json", 1_000)
        new_turn = self._make_turn(tmp_path, "ses-1", "new.json", 3_000)
        workflow = SimpleNamespace(
            all_sessions=[SessionData(session_id="ses-1", files=[old_turn])]
        )
        refreshed_workflow = SimpleNamespace(
            all_sessions=[SessionData(session_id="ses-1", files=[new_turn])]
        )
        monitor._print_recent_turn_picker_table = MagicMock()
        monitor.console.input = MagicMock(side_effect=["r", "1"])
        refresh_workflow = MagicMock(return_value=refreshed_workflow)

        selected = monitor._prompt_for_recent_turn_selection(
            workflow, "Recent Turns", refresh_workflow=refresh_workflow
        )

        assert selected is new_turn
        refresh_workflow.assert_called_once()
        assert monitor._print_recent_turn_picker_table.call_count == 2

    def test_turn_message_and_tool_summaries_use_raw_data(self, tmp_path):
        monitor = LiveMonitor(pricing_data={}, init_from_db=False)
        turn = self._make_turn(tmp_path, "ses-1", "turn.json", 1_000)

        message = monitor._extract_turn_message_summary(turn)
        tools = monitor._extract_turn_tool_summary(turn)

        assert message["user"] == "User request for turn.json"
        assert "Assistant summary" in message["assistant"]
        assert tools == [
            {"tool": "bash", "status": "completed", "summary": "pytest -q"}
        ]

    def test_turn_activity_uses_sqlite_message_metadata_fallback(self, tmp_path):
        monitor = LiveMonitor(pricing_data={}, init_from_db=False)
        turn = self._make_turn(tmp_path, "ses-1", "turn.json", 1_000)
        turn.time_data = None
        turn.raw_data["_message_time_created"] = 10_000
        turn.raw_data["_message_time_updated"] = 12_000

        assert monitor._get_turn_activity_ts(turn) == 12.0

    def test_turn_message_summary_uses_sqlite_part_text_and_user_message(
        self, tmp_path
    ):
        monitor = LiveMonitor(pricing_data={}, init_from_db=False)
        turn = self._make_turn(tmp_path, "ses-1", "turn.json", 1_000)
        turn.raw_data = {
            "role": "assistant",
            "_message_id": "msg-2",
            "_message_time_created": 2_000,
        }
        monitor._load_sqlite_part_payloads_for_turn = MagicMock(
            return_value=[{"type": "text", "text": "Assistant text from part"}]
        )
        monitor._load_sqlite_user_text_for_turn = MagicMock(
            return_value="User text from previous message"
        )

        message = monitor._extract_turn_message_summary(turn)

        assert message["user"] == "User text from previous message"
        assert message["assistant"] == "Assistant text from part"

    def test_recent_turn_picker_preview_includes_user_assistant_and_tools(
        self, tmp_path
    ):
        monitor = LiveMonitor(pricing_data={}, init_from_db=False)
        turn = self._make_turn(tmp_path, "ses-1", "turn.json", 1_000)
        descriptors = monitor._describe_recent_turns(
            SimpleNamespace(all_sessions=[SimpleNamespace(non_zero_token_files=[turn])])
        )
        monitor.console.print = MagicMock()

        monitor._print_recent_turn_picker_table(descriptors, "Recent Turns")

        table = monitor.console.print.call_args.args[0]
        rendered_rows = [str(column._cells[0]) for column in table.columns]
        headers = [column.header for column in table.columns]
        assert "Session" not in headers
        assert headers[4:9] == [
            "Input",
            "Output",
            "Cache Read",
            "Cache Write",
            "Turn Tokens",
        ]
        assert "1,000" in rendered_rows
        assert "100" in rendered_rows
        assert "200" in rendered_rows
        assert "50" in rendered_rows
        assert "1,350" in rendered_rows
        assert any("U: User request" in cell for cell in rendered_rows)
        assert any("A: Assistant summary" in cell for cell in rendered_rows)
        assert any("Tools: bash:completed" in cell for cell in rendered_rows)

    def test_recent_turn_table_marks_cache_miss_rows(self, tmp_path):
        monitor = LiveMonitor(pricing_data={}, init_from_db=False)
        miss = self._make_turn(tmp_path, "ses-1", "miss.json", 1_000)
        miss.tokens.cache_read = 0
        hit = self._make_turn(tmp_path, "ses-1", "hit.json", 2_000)
        hit.tokens.cache_read = 1
        descriptors = monitor._describe_recent_turns(
            SimpleNamespace(all_sessions=[SimpleNamespace(non_zero_token_files=[miss, hit])])
        )

        table = monitor._build_recent_turn_picker_table(descriptors, "Recent Turns")

        assert table.columns[9].header == "Cache"
        assert table.columns[9]._cells == ["—", "MISS"]
        assert table.rows[1].style == "status.warning"
        assert "MISS rows are highlighted" in table.caption
        assert "not a provider miss event" not in table.caption

    def test_recent_turn_table_renders_agent_markup_literally(self, tmp_path):
        monitor = LiveMonitor(pricing_data={}, init_from_db=False)
        turn = self._make_turn(tmp_path, "ses-1", "turn.json", 1_000)
        descriptors = monitor._describe_recent_turns(
            SimpleNamespace(all_sessions=[SimpleNamespace(non_zero_token_files=[turn])])
        )
        descriptors[0]["agent"] = "[red]PWNED[/red]"

        table = monitor._build_recent_turn_picker_table(descriptors, "Recent Turns")

        agent_cell = table.columns[2]._cells[0]
        assert isinstance(agent_cell, Text)
        assert agent_cell.plain == "[red]PWNED[/red]"
        assert all(span.style != "red" for span in agent_cell.spans)

    def test_live_recent_turns_manual_refresh_resets_to_newest_page(
        self, tmp_path, monkeypatch
    ):
        from ocmonitor.models.session import SessionData

        monitor = LiveMonitor(pricing_data={}, init_from_db=False)
        old_turns = [
            self._make_turn(tmp_path, "ses-1", f"old-{idx}.json", idx * 1000)
            for idx in range(51)
        ]
        new_turn = self._make_turn(tmp_path, "ses-1", "newest.json", 99_000)
        initial = SimpleNamespace(all_sessions=[SessionData(session_id="ses-1", files=old_turns)])
        refreshed = SimpleNamespace(all_sessions=[SessionData(session_id="ses-1", files=[new_turn])])
        live = MagicMock()
        monkeypatch.setattr("ocmonitor.services.live_monitor.sys.stdin.isatty", lambda: True)
        monitor._poll_recent_turn_command = MagicMock(side_effect=["n", "R", "q"])
        monkeypatch.setattr("ocmonitor.services.live_monitor.time.monotonic", lambda: 0)
        monkeypatch.setattr("ocmonitor.services.live_monitor.time.sleep", MagicMock())
        refresh_workflow = MagicMock(return_value=refreshed)

        monitor._inspect_recent_turns_during_live(
            live, initial, "Recent Turns", True,
            refresh_workflow=refresh_workflow, refresh_interval=1,
        )

        refresh_workflow.assert_called_once_with()
        assert live.update.call_count >= 3
        final_table = live.update.call_args.args[0].renderables[1]
        assert "1/1" in final_table.title
        assert "1 turns" in final_table.title
        assert monitor._live_status_line == "Ready."

    def test_live_recent_turn_navigation_and_exit(self, tmp_path, monkeypatch):
        from ocmonitor.models.session import SessionData

        monitor = LiveMonitor(pricing_data={}, init_from_db=False)
        turns = [
            self._make_turn(tmp_path, "ses-1", f"turn-{idx}.json", idx * 1000)
            for idx in range(51)
        ]
        workflow = SimpleNamespace(all_sessions=[SessionData(session_id="ses-1", files=turns)])
        live = MagicMock()
        monkeypatch.setattr("ocmonitor.services.live_monitor.sys.stdin.isatty", lambda: True)
        monitor._poll_recent_turn_command = MagicMock(side_effect=["n", "p", "q"])
        monkeypatch.setattr("ocmonitor.services.live_monitor.time.monotonic", lambda: 0)
        monkeypatch.setattr("ocmonitor.services.live_monitor.time.sleep", MagicMock())

        monitor._inspect_recent_turns_during_live(live, workflow, "Recent Turns", True)

        pages = [call.args[0].renderables[1].title for call in live.update.call_args_list]
        assert any("page 2/2" in title for title in pages)
        assert pages[-1].find("page 1/2") >= 0
        assert monitor._live_status_line == "Ready."

    def test_live_recent_turns_empty_initial_view_refreshes(self, monkeypatch):
        from pathlib import Path
        from ocmonitor.models.session import SessionData

        monitor = LiveMonitor(pricing_data={}, init_from_db=False)
        turn = self._make_turn(Path("."), "ses-1", "arrived.json", 1_000)
        initial = SimpleNamespace(all_sessions=[])
        refreshed = SimpleNamespace(all_sessions=[SessionData(session_id="ses-1", files=[turn])])
        live = MagicMock()
        monkeypatch.setattr("ocmonitor.services.live_monitor.sys.stdin.isatty", lambda: True)
        monitor._poll_recent_turn_command = MagicMock(side_effect=[None, "q"])
        monkeypatch.setattr("ocmonitor.services.live_monitor.time.monotonic", MagicMock(side_effect=[0, 1, 1.1]))
        monkeypatch.setattr("ocmonitor.services.live_monitor.time.sleep", MagicMock())

        monitor._inspect_recent_turns_during_live(
            live, initial, "Recent Turns", True,
            refresh_workflow=MagicMock(return_value=refreshed), refresh_interval=1,
        )

        assert "1 turns" in live.update.call_args.args[0].renderables[1].title

    def test_live_recent_turns_auto_refresh_waits_for_page_one(self, tmp_path, monkeypatch):
        from ocmonitor.models.session import SessionData

        monitor = LiveMonitor(pricing_data={}, init_from_db=False)
        turns = [
            self._make_turn(tmp_path, "ses-1", f"turn-{idx}.json", idx * 1000)
            for idx in range(51)
        ]
        initial = SimpleNamespace(all_sessions=[SessionData(session_id="ses-1", files=turns)])
        refreshed = SimpleNamespace(all_sessions=[SessionData(session_id="ses-1", files=turns)])
        live = MagicMock()
        monkeypatch.setattr("ocmonitor.services.live_monitor.sys.stdin.isatty", lambda: True)
        monitor._poll_recent_turn_command = MagicMock(
            side_effect=["n", None, "p", None, "q"]
        )
        monkeypatch.setattr(
            "ocmonitor.services.live_monitor.time.monotonic",
            MagicMock(side_effect=[0, 0.5, 1.1, 1.2, 1.3, 1.4]),
        )
        monkeypatch.setattr("ocmonitor.services.live_monitor.time.sleep", MagicMock())
        refresh_workflow = MagicMock(return_value=refreshed)
        describe_turns = MagicMock(wraps=monitor._describe_recent_turns)
        monitor._describe_recent_turns = describe_turns

        monitor._inspect_recent_turns_during_live(
            live, initial, "Recent Turns", True,
            refresh_workflow=refresh_workflow, refresh_interval=1,
        )

        refresh_workflow.assert_called_once_with()
        assert describe_turns.call_count == 2  # Initial descriptors and resumed refresh only.
        tables = [call.args[0].renderables[1] for call in live.update.call_args_list]
        pages = [table.title for table in tables]
        assert any("page 2/2" in title for title in pages)
        assert pages[-1].find("page 1/2") >= 0
        page_two = next(table for table in tables if "page 2/2" in table.title)
        assert "Auto-refresh paused on page 2 (every 1s on page 1)" in page_two.caption
        assert "Auto-refresh every 1s (page 1)" in tables[-1].caption
        assert "MISS rows are highlighted" in tables[-1].caption
        assert "not a provider miss event" not in tables[-1].caption
        assert "Keys: n/p page" in tables[-1].caption

    def test_live_recent_turns_accepts_multidigit_selection(self, tmp_path, monkeypatch):
        from ocmonitor.models.session import SessionData

        monitor = LiveMonitor(pricing_data={}, init_from_db=False)
        turns = [
            self._make_turn(tmp_path, "ses-1", f"turn-{idx}.json", idx * 1000)
            for idx in range(12)
        ]
        workflow = SimpleNamespace(all_sessions=[SessionData(session_id="ses-1", files=turns)])
        monitor._stdin_fd = 42
        monkeypatch.setattr("ocmonitor.services.live_monitor.sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("ocmonitor.services.live_monitor.select.select", lambda *a, **k: ([sys.stdin], [], []))
        import os
        import sys
        keys = iter([b"1", b"2", b"\n", b"q"])
        monkeypatch.setattr("ocmonitor.services.live_monitor.sys.stdin.isatty", lambda: True)
        monkeypatch.setattr(os, "read", lambda fd, size: next(keys))
        monkeypatch.setattr("ocmonitor.services.live_monitor.time.monotonic", lambda: 0)
        monkeypatch.setattr("ocmonitor.services.live_monitor.time.sleep", MagicMock())
        live = MagicMock()

        monitor._inspect_recent_turns_during_live(live, workflow, "Recent Turns", True)

        assert monitor._live_status_line == "Ready."
        assert any(
            getattr(getattr(call.args[0], "renderables", [None])[0], "title", "").startswith("Turn Details")
            for call in live.update.call_args_list
        )

    def test_live_recent_turns_non_tty_does_not_poll(self, monkeypatch):
        monitor = LiveMonitor(pricing_data={}, init_from_db=False)
        live = MagicMock()
        monkeypatch.setattr("ocmonitor.services.live_monitor.sys.stdin.isatty", lambda: False)
        monitor._poll_recent_turn_command = MagicMock()

        monitor._inspect_recent_turns_during_live(
            live, SimpleNamespace(all_sessions=[]), "Recent Turns", True
        )

        monitor._poll_recent_turn_command.assert_not_called()
        assert "interactive terminal" in monitor._live_status_line

    def test_inspect_recent_turns_keeps_live_running_and_restores_status(self, tmp_path, monkeypatch):
        from ocmonitor.models.session import SessionData

        monitor = LiveMonitor(pricing_data={}, init_from_db=False)
        live = MagicMock()
        turn = self._make_turn(tmp_path, "ses-1", "turn.json", 1_000)
        workflow = SimpleNamespace(all_sessions=[SessionData(session_id="ses-1", files=[turn])])
        monitor._stdin_fd = 9
        monitor._stdin_termios_state = object()
        monitor._poll_recent_turn_command = MagicMock(side_effect=["1", "q"])
        monkeypatch.setattr("ocmonitor.services.live_monitor.sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("ocmonitor.services.live_monitor.time.monotonic", lambda: 0)
        monkeypatch.setattr("ocmonitor.services.live_monitor.time.sleep", MagicMock())

        monitor._inspect_recent_turns_during_live(
            live, workflow, "Recent Turns", True
        )

        live.stop.assert_not_called()
        live.start.assert_not_called()
        assert any(
            getattr(getattr(call.args[0], "renderables", [None])[0], "title", "").startswith("Turn Details")
            for call in live.update.call_args_list
        )
        assert monitor._live_status_line == "Ready."

    def test_inspect_recent_turns_can_select_another_turn(self, tmp_path, monkeypatch):
        from ocmonitor.models.session import SessionData

        monitor = LiveMonitor(pricing_data={}, init_from_db=False)
        live = MagicMock()
        turn_1 = self._make_turn(tmp_path, "ses-1", "turn-1.json", 1_000)
        turn_2 = self._make_turn(tmp_path, "ses-1", "turn-2.json", 2_000)
        workflow = SimpleNamespace(all_sessions=[SessionData(session_id="ses-1", files=[turn_1, turn_2])])
        monitor._poll_recent_turn_command = MagicMock(side_effect=["1", "n", "2", "q"])
        monkeypatch.setattr("ocmonitor.services.live_monitor.sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("ocmonitor.services.live_monitor.time.monotonic", lambda: 0)
        monkeypatch.setattr("ocmonitor.services.live_monitor.time.sleep", MagicMock())

        monitor._inspect_recent_turns_during_live(
            live, workflow, "Recent Turns", True
        )

        details = [
            call.args[0] for call in live.update.call_args_list
            if getattr(getattr(call.args[0], "renderables", [None])[0], "title", "").startswith("Turn Details")
        ]
        assert len(details) == 2

    def test_live_turn_detail_preserves_full_fields_and_tools(self, tmp_path, monkeypatch):
        from ocmonitor.models.session import SessionData

        monitor = LiveMonitor(pricing_data={}, init_from_db=False)
        turn = self._make_turn(tmp_path, "ses-1", "detailed.json", 1_000)
        workflow = SimpleNamespace(all_sessions=[SessionData(session_id="ses-1", files=[turn])])
        monitor._poll_recent_turn_command = MagicMock(side_effect=["1", "q"])
        monkeypatch.setattr("ocmonitor.services.live_monitor.sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("ocmonitor.services.live_monitor.time.monotonic", lambda: 0)
        monkeypatch.setattr("ocmonitor.services.live_monitor.time.sleep", MagicMock())
        live = MagicMock()

        monitor._inspect_recent_turns_during_live(live, workflow, "Recent Turns", True)

        detail_renderables = next(
            call.args[0].renderables for call in live.update.call_args_list
            if any(getattr(item, "title", None) == "Turn Details" for item in call.args[0].renderables)
        )
        panel, tools_table = detail_renderables[:2]
        assert panel.title == "Turn Details"
        detail_labels = [str(cell) for cell in panel.renderable.columns[0]._cells]
        assert {"Project", "Duration", "Finish", "Cache Write", "Total Tokens", "Cost", "Output Rate"}.issubset(detail_labels)
        assert tools_table.title == "Turn Tool Calls"
        assert tools_table.columns[1]._cells == ["bash"]

    def test_poll_live_switch_command_maps_t_to_turns(self, monkeypatch):
        import os
        import select
        import sys

        monitor = LiveMonitor(pricing_data={}, init_from_db=False)
        monitor._stdin_fd = 42
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr(
            select, "select", lambda *args, **kwargs: ([sys.stdin], [], [])
        )
        monkeypatch.setattr(os, "read", lambda fd, size: b"t")

        assert monitor._poll_live_switch_command() == "turns"

    def test_recent_turn_raw_poll_preserves_uppercase_refresh(self, monkeypatch):
        import os
        import select
        import sys

        monitor = LiveMonitor(pricing_data={}, init_from_db=False)
        monitor._stdin_fd = 42
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr(select, "select", lambda *a, **k: ([sys.stdin], [], []))
        monkeypatch.setattr(os, "read", lambda fd, size: b"R")

        assert monitor._poll_recent_turn_command() == "R"

    def test_recent_turn_raw_poll_maps_lowercase_reviewer_without_back_alias(self, monkeypatch):
        import os
        import select
        import sys

        monitor = LiveMonitor(pricing_data={}, init_from_db=False)
        monitor._stdin_fd = 42
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr(select, "select", lambda *a, **k: ([sys.stdin], [], []))
        keys = iter([b"r", b"b"])
        monkeypatch.setattr(os, "read", lambda fd, size: next(keys))

        assert monitor._poll_recent_turn_command() == "r"
        assert monitor._poll_recent_turn_command() == "b"

    def test_live_recent_turn_filter_exact_match_toggle_and_switch(self, tmp_path, monkeypatch):
        from ocmonitor.models.session import SessionData

        monitor = LiveMonitor(pricing_data={}, init_from_db=False)
        turns = [
            self._make_turn(tmp_path, "ses-1", "build.json", 1000, agent="Build"),
            self._make_turn(tmp_path, "ses-1", "bash.json", 2000, agent="bash-executor"),
            self._make_turn(tmp_path, "ses-1", "builder.json", 3000, agent="builder"),
            self._make_turn(tmp_path, "ses-1", "reviewer.json", 4000, agent="Reviewer"),
        ]
        workflow = SimpleNamespace(all_sessions=[SessionData(session_id="ses-1", files=turns)])
        live = MagicMock()
        monkeypatch.setattr("ocmonitor.services.live_monitor.sys.stdin.isatty", lambda: True)
        monitor._poll_recent_turn_command = MagicMock(side_effect=["b", "x", "x", "q"])
        monkeypatch.setattr("ocmonitor.services.live_monitor.time.monotonic", lambda: 0)
        monkeypatch.setattr("ocmonitor.services.live_monitor.time.sleep", MagicMock())

        monitor._inspect_recent_turns_during_live(live, workflow, "Recent Turns", True)

        tables = [call.args[0].renderables[1] for call in live.update.call_args_list]
        assert any("— build" in table.title and "1 turns" in table.title for table in tables)
        assert any("— bash-executor" in table.title and "1 turns" in table.title for table in tables)
        assert any("page 1/1, 4 turns" in table.title for table in tables)
        assert all("builder" not in str(table.rows) for table in tables if "— build" in table.title)

    def test_live_recent_turn_filter_zero_matches_and_filtered_selection(self, tmp_path, monkeypatch):
        from ocmonitor.models.session import SessionData

        monitor = LiveMonitor(pricing_data={}, init_from_db=False)
        turns = [
            self._make_turn(tmp_path, "ses-1", "build.json", 1000, agent="build"),
            self._make_turn(tmp_path, "ses-1", "review.json", 2000, agent="reviewer"),
        ]
        workflow = SimpleNamespace(all_sessions=[SessionData(session_id="ses-1", files=turns)])
        live = MagicMock()
        monitor._poll_recent_turn_command = MagicMock(side_effect=["e", "r", "1", "q"])
        monkeypatch.setattr("ocmonitor.services.live_monitor.sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("ocmonitor.services.live_monitor.time.monotonic", lambda: 0)
        monkeypatch.setattr("ocmonitor.services.live_monitor.time.sleep", MagicMock())

        monitor._inspect_recent_turns_during_live(live, workflow, "Recent Turns", True)

        tables = [call.args[0].renderables[1] for call in live.update.call_args_list]
        assert any("— explore" in table.title and "0 turns" in table.title for table in tables)
        assert any("— reviewer" in table.title and "1 turns" in table.title for table in tables)
        details = [
            call.args[0] for call in live.update.call_args_list
            if hasattr(call.args[0], "renderables")
            and any(getattr(item, "title", None) == "Turn Details" for item in call.args[0].renderables)
        ]
        assert len(details) == 1
        assert details[0].renderables[0].renderable.columns[0]._cells[0] == "Role"

    def test_live_recent_turn_filter_persists_refresh_and_resets_page(self, tmp_path, monkeypatch):
        from ocmonitor.models.session import SessionData

        monitor = LiveMonitor(pricing_data={}, init_from_db=False)
        old = [
            self._make_turn(tmp_path, "ses-1", f"old-{idx}.json", idx * 1000, agent="build")
            for idx in range(51)
        ]
        refreshed = [
            self._make_turn(tmp_path, "ses-1", "new.json", 99_000, agent="BUILD"),
            self._make_turn(tmp_path, "ses-1", "other.json", 98_000, agent="reviewer"),
        ]
        initial = SimpleNamespace(all_sessions=[SessionData(session_id="ses-1", files=old)])
        updated = SimpleNamespace(all_sessions=[SessionData(session_id="ses-1", files=refreshed)])
        live = MagicMock()
        monitor._poll_recent_turn_command = MagicMock(side_effect=["b", "n", "R", "q"])
        monkeypatch.setattr("ocmonitor.services.live_monitor.sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("ocmonitor.services.live_monitor.time.monotonic", lambda: 0)
        monkeypatch.setattr("ocmonitor.services.live_monitor.time.sleep", MagicMock())
        refresh = MagicMock(return_value=updated)

        monitor._inspect_recent_turns_during_live(
            live, initial, "Recent Turns", True, refresh_workflow=refresh
        )

        refresh.assert_called_once_with()
        tables = [call.args[0].renderables[1] for call in live.update.call_args_list]
        assert any("page 2/2" in table.title for table in tables)
        assert "Recent Turns — build (page 1/1, 1 turns)" in tables[-1].title

    def test_live_recent_turn_filter_persists_automatic_refresh(self, tmp_path, monkeypatch):
        from ocmonitor.models.session import SessionData

        monitor = LiveMonitor(pricing_data={}, init_from_db=False)
        turn = self._make_turn(tmp_path, "ses-1", "build.json", 1000, agent="build")
        workflow = SimpleNamespace(all_sessions=[SessionData(session_id="ses-1", files=[turn])])
        live = MagicMock()
        monitor._poll_recent_turn_command = MagicMock(side_effect=["b", None, "q"])
        monkeypatch.setattr("ocmonitor.services.live_monitor.sys.stdin.isatty", lambda: True)
        monkeypatch.setattr(
            "ocmonitor.services.live_monitor.time.monotonic",
            MagicMock(side_effect=[0, 1, 1.1]),
        )
        monkeypatch.setattr("ocmonitor.services.live_monitor.time.sleep", MagicMock())
        refresh = MagicMock(return_value=workflow)

        monitor._inspect_recent_turns_during_live(
            live, workflow, "Recent Turns", True, refresh_workflow=refresh, refresh_interval=1
        )

        refresh.assert_called_once_with()
        tables = [call.args[0].renderables[1] for call in live.update.call_args_list]
        assert tables[-1].title == "Recent Turns — build (page 1/1, 1 turns)"

    def test_recent_turn_footer_shows_filters_and_uppercase_refresh(self, tmp_path):
        monitor = LiveMonitor(pricing_data={}, init_from_db=False)
        turn = self._make_turn(tmp_path, "ses-1", "turn.json", 1000)
        descriptor = monitor._describe_recent_turns(
            SimpleNamespace(all_sessions=[SimpleNamespace(non_zero_token_files=[turn])])
        )

        table = monitor._build_recent_turn_picker_table(descriptor, "Recent Turns")

        for key in ("b=build", "x=bash-executor", "l=lite-worker", "r=reviewer", "e=explore", "R refresh", "q/back return"):
            assert key in str(table.caption)

    def test_recent_turn_filter_aliases_and_filtered_page_pauses_refresh(self, tmp_path, monkeypatch):
        from ocmonitor.models.session import SessionData

        monitor = LiveMonitor(pricing_data={}, init_from_db=False)
        monkeypatch.setattr(monitor, "RECENT_TURN_PAGE_SIZE", 1)
        turns = [
            self._make_turn(tmp_path, "ses-1", "liteworker.json", 1000, agent="LITEWORKER"),
            self._make_turn(tmp_path, "ses-1", "explorer.json", 2000, agent="Explorer"),
            *[
                self._make_turn(tmp_path, "ses-1", f"build-{idx}.json", idx * 1000, agent="build")
                for idx in range(2, 51)
            ],
        ]
        workflow = SimpleNamespace(all_sessions=[SessionData(session_id="ses-1", files=turns)])
        live = MagicMock()
        monitor._poll_recent_turn_command = MagicMock(side_effect=["l", "e", "b", "n", None, "q"])
        monkeypatch.setattr("ocmonitor.services.live_monitor.sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("ocmonitor.services.live_monitor.time.monotonic", lambda: 0)
        monkeypatch.setattr("ocmonitor.services.live_monitor.time.sleep", MagicMock())
        refresh = MagicMock(return_value=workflow)

        monitor._inspect_recent_turns_during_live(
            live, workflow, "Recent Turns", True, refresh_workflow=refresh, refresh_interval=1
        )

        refresh.assert_not_called()
        tables = [call.args[0].renderables[1] for call in live.update.call_args_list]
        assert any("— lite-worker" in table.title and "1 turns" in table.title for table in tables)
        assert any("— explore" in table.title and "1 turns" in table.title for table in tables)
        assert any("— build" in table.title and "page 2/49" in table.title for table in tables)
        assert any("Auto-refresh paused on page 2" in table.caption for table in tables)
