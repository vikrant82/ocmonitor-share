"""Tests for SQLite path discovery behavior."""

import json
from pathlib import Path

from ocmonitor.config import Config, PathsConfig, config_manager
from ocmonitor.utils.sqlite_utils import SQLiteProcessor


class TestFindDatabasePath:
    """Tests for SQLiteProcessor.find_database_path."""

    def test_prefers_custom_path_over_env_and_config(self, monkeypatch, tmp_path: Path):
        """Explicit custom path should have highest precedence."""
        custom_db = tmp_path / "custom.db"
        custom_db.touch()

        env_db = tmp_path / "env.db"
        env_db.touch()
        monkeypatch.setenv("OCMONITOR_DATABASE_FILE", str(env_db))

        configured_db = tmp_path / "configured.db"
        configured_db.touch()
        monkeypatch.setattr(
            config_manager,
            "_config",
            Config(paths=PathsConfig(database_file=str(configured_db))),
        )

        monkeypatch.setattr(SQLiteProcessor, "DEFAULT_DB_PATH", tmp_path / "default.db")

        resolved = SQLiteProcessor.find_database_path(custom_db)

        assert resolved == custom_db

    def test_uses_configured_database_file_when_default_missing(
        self, monkeypatch, tmp_path: Path
    ):
        """Config path should be used when default path does not exist."""
        configured_db = tmp_path / "configured.db"
        configured_db.touch()

        monkeypatch.delenv("OCMONITOR_DATABASE_FILE", raising=False)
        monkeypatch.setattr(
            config_manager,
            "_config",
            Config(paths=PathsConfig(database_file=str(configured_db))),
        )
        monkeypatch.setattr(
            SQLiteProcessor, "DEFAULT_DB_PATH", tmp_path / "missing-default.db"
        )

        resolved = SQLiteProcessor.find_database_path()

        assert resolved == configured_db

    def test_falls_back_to_default_when_configured_path_invalid(
        self, monkeypatch, tmp_path: Path
    ):
        """Default path should be used when configured path is invalid."""
        missing_configured = tmp_path / "missing-configured.db"
        default_db = tmp_path / "default.db"
        default_db.touch()

        monkeypatch.delenv("OCMONITOR_DATABASE_FILE", raising=False)
        monkeypatch.setattr(
            config_manager,
            "_config",
            Config(paths=PathsConfig(database_file=str(missing_configured))),
        )
        monkeypatch.setattr(SQLiteProcessor, "DEFAULT_DB_PATH", default_db)

        resolved = SQLiteProcessor.find_database_path()

        assert resolved == default_db


class TestParseMessageData:
    """Tests for SQLiteProcessor.parse_message_data."""

    def test_parse_null_provider_id(self):
        """providerID=null should not crash and should map to None."""
        message = json.dumps(
            {
                "role": "assistant",
                "modelID": "test-model",
                "providerID": None,
                "tokens": {"input": 1000, "output": 500},
            }
        )

        result = SQLiteProcessor.parse_message_data(message, "ses_test")

        assert result is not None
        assert result.provider_id is None

    def test_null_model_id_falls_back_to_unknown(self):
        """Null modelID in SQLite message payload should not break parsing."""
        message_data = json.dumps({"role": "assistant", "modelID": None})

        interaction = SQLiteProcessor.parse_message_data(message_data, "ses_test")

        assert interaction is not None
        assert interaction.model_id == "unknown"

    def test_nested_null_model_id_falls_back_to_unknown(self):
        """Null nested model.modelID in SQLite payload should fall back to unknown."""
        message_data = json.dumps({"role": "assistant", "model": {"modelID": None}})

        interaction = SQLiteProcessor.parse_message_data(message_data, "ses_test")

        assert interaction is not None
        assert interaction.model_id == "unknown"

    def test_parse_message_data_preserves_sqlite_message_metadata(self):
        """SQLite message metadata should be available for turn detail part lookup."""
        message_data = json.dumps(
            {"role": "assistant", "modelID": "test-model", "tokens": {"input": 1}}
        )

        interaction = SQLiteProcessor.parse_message_data(
            message_data,
            "ses_test",
            message_id="msg_test",
            time_created=123,
            time_updated=456,
        )

        assert interaction is not None
        assert interaction.raw_data["_message_id"] == "msg_test"
        assert interaction.raw_data["_message_time_created"] == 123
        assert interaction.raw_data["_message_time_updated"] == 456
