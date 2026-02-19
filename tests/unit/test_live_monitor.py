import logging
from unittest.mock import MagicMock, patch
from ocmonitor.config import PathsConfig
from ocmonitor.services.live_monitor import LiveMonitor


class TestMultiWorkflowTracking:
    def test_tracks_multiple_active_workflows(self, monkeypatch, tmp_path):
        active_workflow_a = {
            "workflow_id": "session-a",
            "main_session": MagicMock(session_id="session-a", end_time=None),
            "all_sessions": [MagicMock(session_id="session-a")],
        }
        active_workflow_b = {
            "workflow_id": "session-b",
            "main_session": MagicMock(session_id="session-b", end_time=None),
            "all_sessions": [MagicMock(session_id="session-b")],
        }

        monkeypatch.setattr(
            "ocmonitor.services.live_monitor.SQLiteProcessor.find_database_path",
            lambda: str(tmp_path / "test.db"),
        )
        monkeypatch.setattr(
            "ocmonitor.services.live_monitor.SQLiteProcessor.get_all_active_workflows",
            lambda db_path: [active_workflow_a, active_workflow_b],
        )

        paths_config = PathsConfig(messages_dir=str(tmp_path))
        monitor = LiveMonitor(pricing_data={}, paths_config=paths_config)

        assert monitor._get_tracked_workflow_ids() == {"session-a", "session-b"}

    def test_removes_ended_workflow_from_tracking(self, monkeypatch, tmp_path):
        ended_workflow = {
            "workflow_id": "session-ended",
            "main_session": MagicMock(session_id="session-ended", end_time=1000),
            "all_sessions": [MagicMock(session_id="session-ended")],
        }
        active_workflow = {
            "workflow_id": "session-active",
            "main_session": MagicMock(session_id="session-active", end_time=None),
            "all_sessions": [MagicMock(session_id="session-active")],
        }

        call_count = [0]

        def mock_get_workflows(db_path):
            call_count[0] += 1
            if call_count[0] == 1:
                return [ended_workflow, active_workflow]
            return [active_workflow]

        monkeypatch.setattr(
            "ocmonitor.services.live_monitor.SQLiteProcessor.find_database_path",
            lambda: str(tmp_path / "test.db"),
        )
        monkeypatch.setattr(
            "ocmonitor.services.live_monitor.SQLiteProcessor.get_all_active_workflows",
            mock_get_workflows,
        )

        paths_config = PathsConfig(messages_dir=str(tmp_path))
        monitor = LiveMonitor(pricing_data={}, paths_config=paths_config)

        assert monitor._get_tracked_workflow_ids() == {
            "session-ended",
            "session-active",
        }

        monitor._refresh_active_workflows(str(tmp_path / "test.db"))

        assert monitor._get_tracked_workflow_ids() == {"session-active"}

    def test_displays_most_recently_active_workflow(self, monkeypatch, tmp_path):
        now = 1700000000
        older_workflow = {
            "workflow_id": "session-old",
            "main_session": MagicMock(
                session_id="session-old",
                end_time=None,
                start_time=now - 3600,
            ),
            "all_sessions": [MagicMock(session_id="session-old")],
        }
        newer_workflow = {
            "workflow_id": "session-new",
            "main_session": MagicMock(
                session_id="session-new",
                end_time=None,
                start_time=now,
            ),
            "all_sessions": [MagicMock(session_id="session-new")],
        }

        monkeypatch.setattr(
            "ocmonitor.services.live_monitor.SQLiteProcessor.find_database_path",
            lambda: str(tmp_path / "test.db"),
        )
        monkeypatch.setattr(
            "ocmonitor.services.live_monitor.SQLiteProcessor.get_all_active_workflows",
            lambda db_path: [older_workflow, newer_workflow],
        )

        paths_config = PathsConfig(messages_dir=str(tmp_path))
        monitor = LiveMonitor(pricing_data={}, paths_config=paths_config)

        displayed = monitor._get_displayed_workflow()
        assert displayed["workflow_id"] == "session-new"

    def test_prev_tracked_reset_on_workflow_switch(self, monkeypatch, tmp_path):
        now = 1700000000
        workflow_a = {
            "workflow_id": "workflow-a",
            "main_session": MagicMock(
                session_id="workflow-a",
                end_time=None,
                start_time=now - 3600,
            ),
            "all_sessions": [
                MagicMock(session_id="session-a1"),
                MagicMock(session_id="session-a2"),
            ],
        }
        workflow_b = {
            "workflow_id": "workflow-b",
            "main_session": MagicMock(
                session_id="workflow-b",
                end_time=None,
                start_time=now,
            ),
            "all_sessions": [
                MagicMock(session_id="session-b1"),
            ],
        }

        call_count = [0]

        def mock_get_workflows(db_path):
            call_count[0] += 1
            if call_count[0] == 1:
                return [workflow_a]
            return [workflow_b]

        monkeypatch.setattr(
            "ocmonitor.services.live_monitor.SQLiteProcessor.find_database_path",
            lambda: str(tmp_path / "test.db"),
        )
        monkeypatch.setattr(
            "ocmonitor.services.live_monitor.SQLiteProcessor.get_all_active_workflows",
            mock_get_workflows,
        )

        paths_config = PathsConfig(messages_dir=str(tmp_path))
        monitor = LiveMonitor(pricing_data={}, paths_config=paths_config)

        assert monitor._get_displayed_workflow()["workflow_id"] == "workflow-a"
        assert monitor.prev_tracked == {"session-a1", "session-a2"}

        monitor._refresh_active_workflows(str(tmp_path / "test.db"))

        assert monitor._get_displayed_workflow()["workflow_id"] == "workflow-b"
        assert monitor.prev_tracked == set()

    def test_detects_new_sub_agent_during_poll(self, monkeypatch, tmp_path):
        now = 1700000000
        main_session = MagicMock(
            session_id="main-session",
            end_time=None,
            start_time=now,
        )

        workflow_initial = {
            "workflow_id": "workflow-with-subagents",
            "main_session": main_session,
            "all_sessions": [main_session],
            "sub_agents": [],
            "sub_agent_count": 0,
            "has_sub_agents": False,
        }

        sub_agent = MagicMock(
            session_id="sub-agent-1",
            end_time=None,
            start_time=now + 100,
        )

        workflow_with_subagent = {
            "workflow_id": "workflow-with-subagents",
            "main_session": main_session,
            "all_sessions": [main_session, sub_agent],
            "sub_agents": [sub_agent],
            "sub_agent_count": 1,
            "has_sub_agents": True,
        }

        call_count = [0]

        def mock_get_workflows(db_path):
            call_count[0] += 1
            if call_count[0] == 1:
                return [workflow_initial]
            return [workflow_with_subagent]

        monkeypatch.setattr(
            "ocmonitor.services.live_monitor.SQLiteProcessor.find_database_path",
            lambda: str(tmp_path / "test.db"),
        )
        monkeypatch.setattr(
            "ocmonitor.services.live_monitor.SQLiteProcessor.get_all_active_workflows",
            mock_get_workflows,
        )

        paths_config = PathsConfig(messages_dir=str(tmp_path))
        monitor = LiveMonitor(pricing_data={}, paths_config=paths_config)

        assert monitor.prev_tracked == {"main-session"}

        monitor._refresh_active_workflows(str(tmp_path / "test.db"))

        assert monitor.prev_tracked == {"main-session", "sub-agent-1"}

    def test_no_false_sub_agent_detection_on_workflow_switch(
        self, monkeypatch, tmp_path, caplog
    ):
        now = 1700000000
        workflow_a = {
            "workflow_id": "workflow-a",
            "main_session": MagicMock(
                session_id="session-a-main",
                end_time=None,
                start_time=now - 3600,
            ),
            "all_sessions": [
                MagicMock(session_id="session-a-main"),
                MagicMock(session_id="session-a-sub"),
            ],
        }
        workflow_b = {
            "workflow_id": "workflow-b",
            "main_session": MagicMock(
                session_id="session-b-main",
                end_time=None,
                start_time=now,
            ),
            "all_sessions": [
                MagicMock(session_id="session-b-main"),
                MagicMock(session_id="session-b-sub1"),
                MagicMock(session_id="session-b-sub2"),
            ],
        }

        call_count = [0]

        def mock_get_workflows(db_path):
            call_count[0] += 1
            if call_count[0] == 1:
                return [workflow_a]
            return [workflow_b]

        monkeypatch.setattr(
            "ocmonitor.services.live_monitor.SQLiteProcessor.find_database_path",
            lambda: str(tmp_path / "test.db"),
        )
        monkeypatch.setattr(
            "ocmonitor.services.live_monitor.SQLiteProcessor.get_all_active_workflows",
            mock_get_workflows,
        )

        paths_config = PathsConfig(messages_dir=str(tmp_path))
        monitor = LiveMonitor(pricing_data={}, paths_config=paths_config)

        assert monitor._get_displayed_workflow()["workflow_id"] == "workflow-a"
        assert monitor.prev_tracked == {
            "session-a-main",
            "session-a-sub",
        }, "prev_tracked initialized with workflow-a sessions"

        caplog.set_level(logging.INFO)
        monitor._refresh_active_workflows(str(tmp_path / "test.db"))

        assert monitor._get_displayed_workflow()["workflow_id"] == "workflow-b"
        assert monitor.prev_tracked == set(), (
            "prev_tracked should be empty after switching workflows; "
            "if it contained workflow-a sessions, they would interfere with tracking"
        )

        assert "New sub-agent detected" not in caplog.text, (
            "workflow-b sessions should NOT be falsely detected as new sub-agents "
            "even though prev_tracked had workflow-a sessions before the switch"
        )

        monitor._refresh_active_workflows(str(tmp_path / "test.db"))
        assert monitor.prev_tracked == {
            "session-b-main",
            "session-b-sub1",
            "session-b-sub2",
        }, "prev_tracked now tracks workflow-b sessions after stable refresh"


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
