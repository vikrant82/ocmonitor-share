from ocmonitor.config import PathsConfig
from ocmonitor.services.live_monitor import LiveMonitor


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
