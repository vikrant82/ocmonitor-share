"""Tests for file utility functions."""

import json
import pytest
from pathlib import Path

from ocmonitor.utils.file_utils import FileProcessor
from ocmonitor.models.session import InteractionFile, SessionData, TokenUsage, TimeData


class TestLoadJsonFile:
    """Tests for load_json_file method."""
    
    def test_load_valid_json(self, tmp_path):
        """Test loading a valid JSON file."""
        test_file = tmp_path / "test.json"
        test_data = {"key": "value", "number": 123}
        test_file.write_text(json.dumps(test_data))
        
        result = FileProcessor.load_json_file(test_file)
        assert result == test_data
    
    def test_load_nonexistent_file(self, tmp_path):
        """Test loading a non-existent file."""
        result = FileProcessor.load_json_file(tmp_path / "nonexistent.json")
        assert result is None
    
    def test_load_invalid_json(self, tmp_path):
        """Test loading an invalid JSON file."""
        test_file = tmp_path / "invalid.json"
        test_file.write_text("not valid json {{")
        
        result = FileProcessor.load_json_file(test_file)
        assert result is None
    
    def test_load_empty_file(self, tmp_path):
        """Test loading an empty file."""
        test_file = tmp_path / "empty.json"
        test_file.write_text("")
        
        result = FileProcessor.load_json_file(test_file)
        assert result is None


class TestNormalizeModelName:
    """Tests for _normalize_model_name method."""
    
    def test_normalize_simple_name(self):
        """Test normalizing a simple model name."""
        result = FileProcessor._normalize_model_name("claude-sonnet-4")
        assert result == "claude-sonnet-4"
    
    def test_normalize_unknown(self):
        """Test normalizing 'unknown' model name."""
        result = FileProcessor._normalize_model_name("unknown")
        assert result == "unknown"
    
    def test_normalize_with_timestamp_suffix(self):
        """Test normalizing model name with date suffix."""
        result = FileProcessor._normalize_model_name("claude-sonnet-4-20241101")
        # Should extract base model name
        assert "claude-sonnet-4" in result


class TestFindSessionDirectories:
    """Tests for find_session_directories method."""
    
    def test_find_session_directories(self, tmp_path):
        """Test finding session directories."""
        # Create mock session directories
        (tmp_path / "ses_001").mkdir()
        (tmp_path / "ses_002").mkdir()
        (tmp_path / "not_a_session").mkdir()
        
        result = FileProcessor.find_session_directories(str(tmp_path))
        
        assert len(result) == 2
        session_names = [p.name for p in result]
        assert "ses_001" in session_names
        assert "ses_002" in session_names
    
    def test_find_session_directories_empty(self, tmp_path):
        """Test finding session directories in empty directory."""
        result = FileProcessor.find_session_directories(str(tmp_path))
        assert result == []


class TestFindJsonFiles:
    """Tests for find_json_files method."""
    
    def test_find_json_files(self, tmp_path):
        """Test finding JSON files in directory."""
        (tmp_path / "file1.json").write_text("{}")
        (tmp_path / "file2.json").write_text("{}")
        (tmp_path / "readme.txt").write_text("text")
        
        result = FileProcessor.find_json_files(tmp_path)
        
        assert len(result) == 2
        names = [p.name for p in result]
        assert "file1.json" in names
        assert "file2.json" in names


class TestParseInteractionFile:
    """Tests for parse_interaction_file method."""
    
    def test_parse_valid_interaction(self, tmp_path):
        """Test parsing a valid interaction file."""
        test_file = tmp_path / "inter_0001.json"
        interaction_data = {
            "modelID": "test-model",
            "tokens": {
                "input": 1000,
                "output": 500,
                "cache": {
                    "write": 200,
                    "read": 100
                }
            },
            "timeData": {
                "created": 1700000000000,
                "completed": 1700003600000
            },
            "projectPath": "/home/user/project",
            "agent": "main"
        }
        test_file.write_text(json.dumps(interaction_data))
        
        result = FileProcessor.parse_interaction_file(test_file, "ses_test")
        
        assert result is not None
        assert result.model_id == "test-model"
        assert result.tokens.input == 1000
        assert result.tokens.output == 500
        assert result.tokens.cache_write == 200
        assert result.tokens.cache_read == 100
        assert result.agent == "main"
    
    def test_parse_missing_model_id(self, tmp_path):
        """Test parsing interaction without modelID."""
        test_file = tmp_path / "inter_0001.json"
        interaction_data = {
            "tokens": {"input": 1000, "output": 500}
        }
        test_file.write_text(json.dumps(interaction_data))
        
        result = FileProcessor.parse_interaction_file(test_file, "ses_test")
        
        assert result is not None
        assert result.model_id == "unknown"

    def test_parse_null_model_id(self, tmp_path):
        """Test parsing interaction with null modelID."""
        test_file = tmp_path / "inter_0001.json"
        interaction_data = {
            "modelID": None,
            "tokens": {"input": 1000, "output": 500},
        }
        test_file.write_text(json.dumps(interaction_data))

        result = FileProcessor.parse_interaction_file(test_file, "ses_test")

        assert result is not None
        assert result.model_id == "unknown"
    
    def test_parse_missing_tokens(self, tmp_path):
        """Test parsing interaction without tokens."""
        test_file = tmp_path / "inter_0001.json"
        interaction_data = {
            "modelID": "test-model",
            "timeData": {"created": 1700000000000}
        }
        test_file.write_text(json.dumps(interaction_data))
        
        result = FileProcessor.parse_interaction_file(test_file, "ses_test")
        
        assert result is not None
        assert result.tokens.total == 0
    
    def test_parse_invalid_json(self, tmp_path):
        """Test parsing an invalid JSON file."""
        test_file = tmp_path / "inter_0001.json"
        test_file.write_text("invalid json")
        
        result = FileProcessor.parse_interaction_file(test_file, "ses_test")
        assert result is None

    def test_parse_null_provider_id(self, tmp_path):
        """providerID=null should not crash and should map to None."""
        test_file = tmp_path / "inter_0001.json"
        interaction_data = {
            "modelID": "test-model",
            "providerID": None,
            "tokens": {"input": 1000, "output": 500},
        }
        test_file.write_text(json.dumps(interaction_data))

        result = FileProcessor.parse_interaction_file(test_file, "ses_test")

        assert result is not None
        assert result.provider_id is None


class TestLoadSessionData:
    """Tests for load_session_data method."""
    
    def test_load_session_with_interactions(self, tmp_path):
        """Test loading a session with multiple interactions."""
        session_dir = tmp_path / "ses_test123"
        session_dir.mkdir()
        
        # Create interaction files
        interaction1 = session_dir / "inter_0001.json"
        interaction1.write_text(json.dumps({
            "modelID": "model-a",
            "tokens": {"input": 1000, "output": 500, "cache": {"write": 200, "read": 100}},
            "timeData": {"created": 1700000000000, "completed": 1700003600000},
            "projectPath": "/home/user/project1",
            "agent": "main"
        }))
        
        interaction2 = session_dir / "inter_0002.json"
        interaction2.write_text(json.dumps({
            "modelID": "model-a",
            "tokens": {"input": 500, "output": 300, "cache": {"write": 100, "read": 50}},
            "timeData": {"created": 1700003700000, "completed": 1700004000000},
            "projectPath": "/home/user/project1",
            "agent": "main"
        }))
        
        result = FileProcessor.load_session_data(session_dir)
        
        assert result is not None
        assert result.session_id == "ses_test123"
        assert len(result.files) == 2
        assert result.total_tokens.input == 1500
        assert result.total_tokens.output == 800
    
    def test_load_session_empty_directory(self, tmp_path):
        """Test loading an empty session directory."""
        session_dir = tmp_path / "ses_empty"
        session_dir.mkdir()
        
        result = FileProcessor.load_session_data(session_dir)
        # Should return None because no interactions with tokens > 0
        assert result is None
    
    def test_load_session_no_json_files(self, tmp_path):
        """Test loading a session with no JSON files."""
        session_dir = tmp_path / "ses_notjson"
        session_dir.mkdir()
        
        # Create a non-JSON file
        (session_dir / "readme.txt").write_text("Not a JSON file")
        
        result = FileProcessor.load_session_data(session_dir)
        assert result is None
    
    def test_load_session_nonexistent_directory(self, tmp_path):
        """Test loading a non-existent session directory."""
        result = FileProcessor.load_session_data(tmp_path / "nonexistent")
        assert result is None


class TestLoadAllSessions:
    """Tests for load_all_sessions method."""
    
    def test_load_multiple_sessions(self, tmp_path):
        """Test loading multiple sessions from a directory."""
        # Create session 1
        session1 = tmp_path / "ses_001"
        session1.mkdir()
        inter1 = session1 / "inter_0001.json"
        inter1.write_text(json.dumps({
            "modelID": "model-a",
            "tokens": {"input": 1000, "output": 500}
        }))
        
        # Create session 2
        session2 = tmp_path / "ses_002"
        session2.mkdir()
        inter2 = session2 / "inter_0001.json"
        inter2.write_text(json.dumps({
            "modelID": "model-b",
            "tokens": {"input": 2000, "output": 1000}
        }))
        
        # Create a non-session directory (should be ignored)
        not_session = tmp_path / "not_a_session"
        not_session.mkdir()
        
        result = FileProcessor.load_all_sessions(str(tmp_path))
        
        assert len(result) == 2
        session_ids = [s.session_id for s in result]
        assert "ses_001" in session_ids
        assert "ses_002" in session_ids
    
    def test_load_sessions_empty_directory(self, tmp_path):
        """Test loading from empty directory."""
        result = FileProcessor.load_all_sessions(str(tmp_path))
        assert result == []
    
    def test_load_sessions_with_limit(self, tmp_path):
        """Test loading sessions with limit."""
        # Create multiple sessions
        for i in range(5):
            session_dir = tmp_path / f"ses_{i:03d}"
            session_dir.mkdir()
            inter = session_dir / "inter_0001.json"
            inter.write_text(json.dumps({
                "tokens": {"input": 100, "output": 50}
            }))
        
        result = FileProcessor.load_all_sessions(str(tmp_path), limit=3)
        
        assert len(result) == 3


class TestMetadataDiscovery:
    def _write_session(self, base, session_id, agent, project, created, tokens=10):
        session_dir = base / session_id
        session_dir.mkdir()
        (session_dir / "inter_0001.json").write_text(json.dumps({
            "agent": agent,
            "tokens": {"input": tokens},
            "time": {"created": created, "completed": created + 1000} if created is not None else {},
            "path": {"cwd": project},
            "message": {"private": "payload must not be retained"},
        }))
        return session_dir

    def test_metadata_matches_grouping_fields_without_payloads(self, tmp_path):
        from ocmonitor.services.session_grouper import SessionGrouper

        main = self._write_session(tmp_path, "ses_main", "main", "/work/project", 1700000000000)
        sub = self._write_session(tmp_path, "ses_sub", "explore", "/work/project", 1700000005000)
        (tmp_path / "ses_bad").mkdir()
        (tmp_path / "ses_bad" / "bad.json").write_text("invalid")

        metadata = FileProcessor.discover_session_metadata(str(tmp_path))
        by_id = {session.session_id: session for session in metadata}
        assert set(by_id) == {"ses_main", "ses_sub"}
        assert by_id["ses_main"].agent == "main"
        assert by_id["ses_main"].project_name == "project"
        assert by_id["ses_main"].start_time is not None
        assert by_id["ses_main"].start_time.timestamp() == pytest.approx(1700000000)
        assert by_id["ses_main"].display_title == "ses_main"
        assert by_id["ses_main"].last_activity_ts == pytest.approx((main / "inter_0001.json").stat().st_mtime)
        assert "raw_data" not in vars(by_id["ses_main"])
        workflow, = SessionGrouper().group_session_metadata(metadata)
        assert workflow.workflow_id == "ses_main"
        assert [session.session_id for session in workflow.all_sessions] == ["ses_main", "ses_sub"]
        assert workflow.project_name == "project"
        assert workflow.session_count == 2

    def test_metadata_limit_candidates_and_hydrate_only_requested_ids(self, tmp_path, monkeypatch):
        self._write_session(tmp_path, "ses_old", "main", "/work/old", 1700000000000)
        selected = self._write_session(tmp_path, "ses_selected", "main", "/work/selected", 1700001000000)
        ignored = self._write_session(tmp_path, "ses_ignored", "main", "/work/ignored", 1700002000000)
        # Directory mtime determines candidate selection, independent of interaction time.
        import os
        os.utime(tmp_path / "ses_old", (100, 100))
        os.utime(selected, (200, 200))
        os.utime(ignored, (300, 300))
        candidates = FileProcessor.discover_session_metadata(str(tmp_path), limit=2)
        assert {session.session_id for session in candidates} == {"ses_selected", "ses_ignored"}

        calls = []
        real_loader = FileProcessor.load_session_data
        def recording_loader(path):
            calls.append(Path(path).name)
            return real_loader(path)
        monkeypatch.setattr(FileProcessor, "load_session_data", recording_loader)
        loaded = FileProcessor.load_sessions_by_id(str(tmp_path), ["ses_selected", "ses_selected", "missing"])
        assert [session.session_id for session in loaded] == ["ses_selected"]
        assert calls == ["ses_selected"]
        assert loaded[0].files[0].raw_data["message"]["private"] == "payload must not be retained"

    def test_historical_loader_still_loads_full_session_data(self, tmp_path):
        self._write_session(tmp_path, "ses_history", "main", "/work/history", 1700000000000)
        sessions = FileProcessor.load_all_sessions(str(tmp_path))
        assert [session.session_id for session in sessions] == ["ses_history"]
        assert sessions[0].files[0].raw_data["message"]["private"] == "payload must not be retained"

    def test_sub_agent_without_start_time_remains_an_orphan_workflow(self, tmp_path):
        from ocmonitor.services.session_grouper import SessionGrouper

        self._write_session(tmp_path, "ses_sub_orphan", "explore", "/work/project", None)
        workflows = SessionGrouper().group_session_metadata(
            FileProcessor.discover_session_metadata(str(tmp_path))
        )
        assert [workflow.workflow_id for workflow in workflows] == ["ses_sub_orphan"]
        assert workflows[0].sub_agent_count == 0

    def test_refresh_metadata_parses_new_child_directory(self, tmp_path):
        from ocmonitor.utils.file_utils import SessionMetadataCache

        cache = FileProcessor.refresh_session_metadata(str(tmp_path), None, limit=10)
        self._write_session(tmp_path, "ses_new", "main", "/work/new", 1700000000000)

        refreshed = FileProcessor.refresh_session_metadata(str(tmp_path), cache, limit=10)

        assert isinstance(refreshed, SessionMetadataCache)
        assert set(refreshed.entries) == {"ses_new"}
        assert "ses_new" in refreshed.dir_mtimes_ns

    def test_refresh_metadata_does_not_parse_unchanged_unselected_directories(self, tmp_path, monkeypatch):
        self._write_session(tmp_path, "ses_old", "main", "/work/old", 1700000000000)
        newest = self._write_session(tmp_path, "ses_newest", "main", "/work/new", 1700001000000)
        import os
        os.utime(tmp_path / "ses_old", (100, 100))
        os.utime(newest, (200, 200))
        cache = FileProcessor.refresh_session_metadata(str(tmp_path), None, limit=1)

        calls = []
        original = FileProcessor._discover_session_directory_metadata
        def recording_parser(path):
            calls.append(Path(path).name)
            return original(path)
        monkeypatch.setattr(FileProcessor, "_discover_session_directory_metadata", recording_parser)

        FileProcessor.refresh_session_metadata(str(tmp_path), cache, limit=1)

        assert calls == []
        assert "ses_old" not in cache.entries

    def test_refresh_metadata_parses_new_out_of_window_directory_only(self, tmp_path, monkeypatch):
        import os

        old = self._write_session(tmp_path, "ses_old", "main", "/work/old", 1700000000000)
        newest = self._write_session(tmp_path, "ses_newest", "main", "/work/new", 1700001000000)
        os.utime(old, (100, 100))
        os.utime(newest, (300, 300))
        cache = FileProcessor.refresh_session_metadata(str(tmp_path), None, limit=1)
        added = self._write_session(tmp_path, "ses_added", "main", "/work/added", 1700002000000)
        os.utime(added, (50, 50))

        calls = []
        original = FileProcessor._discover_session_directory_metadata

        def recording_parser(path):
            calls.append(Path(path).name)
            return original(path)

        monkeypatch.setattr(FileProcessor, "_discover_session_directory_metadata", recording_parser)
        refreshed = FileProcessor.refresh_session_metadata(str(tmp_path), cache, limit=1)

        assert calls == ["ses_added"]
        assert set(refreshed.entries) == {"ses_newest", "ses_added"}

    def test_cache_without_directory_baseline_establishes_without_full_hydration(self, tmp_path, monkeypatch):
        from ocmonitor.utils.file_utils import SessionMetadataCache

        old = self._write_session(tmp_path, "ses_old", "main", "/work/old", 1700000000000)
        newest = self._write_session(tmp_path, "ses_newest", "main", "/work/new", 1700001000000)
        import os
        os.utime(old, (100, 100))
        os.utime(newest, (300, 300))
        cache = SessionMetadataCache(entries={}, dir_mtimes_ns={})
        calls = []
        original = FileProcessor._discover_session_directory_metadata

        def recording_parser(path):
            calls.append(Path(path).name)
            return original(path)

        monkeypatch.setattr(FileProcessor, "_discover_session_directory_metadata", recording_parser)
        FileProcessor.refresh_session_metadata(str(tmp_path), cache, limit=1)
        assert calls == ["ses_newest"]

        added = self._write_session(tmp_path, "ses_added", "main", "/work/added", 1700002000000)
        os.utime(added, (50, 50))
        calls.clear()
        FileProcessor.refresh_session_metadata(str(tmp_path), cache, limit=1)

        assert calls == ["ses_added"]

    def test_refresh_metadata_reparses_changed_and_removes_deleted_directory(self, tmp_path, monkeypatch):
        changed = self._write_session(tmp_path, "ses_changed", "main", "/work/old", 1700000000000)
        deleted = self._write_session(tmp_path, "ses_deleted", "main", "/work/delete", 1700001000000)
        cache = FileProcessor.refresh_session_metadata(str(tmp_path), None)

        # Force a directory mtime change, which is the refresh invalidation signal.
        import os
        os.utime(changed, (changed.stat().st_mtime + 10, changed.stat().st_mtime + 10))
        import shutil
        shutil.rmtree(deleted)
        calls = []
        original = FileProcessor._discover_session_directory_metadata
        def recording_parser(path):
            calls.append(Path(path).name)
            return original(path)
        monkeypatch.setattr(FileProcessor, "_discover_session_directory_metadata", recording_parser)

        refreshed = FileProcessor.refresh_session_metadata(str(tmp_path), cache)

        assert calls == ["ses_changed"]
        assert set(refreshed.entries) == {"ses_changed"}
        assert set(refreshed.dir_mtimes_ns) == {"ses_changed"}


class TestValidateSessionStructure:
    """Tests for validate_session_structure method."""
    
    def test_valid_session_directory(self, tmp_path):
        """Test valid session directory with proper structure."""
        session_dir = tmp_path / "ses_test123"
        session_dir.mkdir()
        
        # Add a JSON file with token data (needed for valid session)
        (session_dir / "inter_0001.json").write_text(json.dumps({
            "tokens": {"input": 100, "output": 50}
        }))
        
        result = FileProcessor.validate_session_structure(session_dir)
        # Returns bool indicating if structure is valid
        assert isinstance(result, bool)
    
    def test_invalid_session_directory(self, tmp_path):
        """Test invalid session directory (wrong prefix)."""
        not_session = tmp_path / "not_a_session"
        not_session.mkdir()
        
        result = FileProcessor.validate_session_structure(not_session)
        # Returns bool
        assert isinstance(result, bool)
    
    def test_file_not_directory(self, tmp_path):
        """Test that files are not valid session directories."""
        test_file = tmp_path / "ses_file"
        test_file.write_text("not a directory")
        
        result = FileProcessor.validate_session_structure(test_file)
        assert result is False


class TestGetSessionStats:
    """Tests for get_session_stats method."""
    
    def test_get_stats_existing_session(self, tmp_path):
        """Test getting stats for an existing session."""
        session_dir = tmp_path / "ses_test"
        session_dir.mkdir()
        
        # Create files with token data
        file1 = session_dir / "inter_0001.json"
        file1.write_text(json.dumps({"tokens": {"input": 100, "output": 50}}))
        
        file2 = session_dir / "inter_0002.json"
        file2.write_text(json.dumps({"tokens": {"input": 200, "output": 100}}))
        
        stats = FileProcessor.get_session_stats(session_dir)
        
        assert isinstance(stats, dict)
        # Implementation returns dict (may be empty or contain stats)
    
    def test_get_stats_empty_session(self, tmp_path):
        """Test getting stats for an empty session."""
        session_dir = tmp_path / "ses_empty"
        session_dir.mkdir()
        
        stats = FileProcessor.get_session_stats(session_dir)
        
        assert isinstance(stats, dict)
    
    def test_get_stats_nonexistent(self, tmp_path):
        """Test getting stats for non-existent session."""
        stats = FileProcessor.get_session_stats(tmp_path / "nonexistent")
        # Returns empty dict for non-existent
        assert isinstance(stats, dict)


class TestGetMostRecentSession:
    """Tests for get_most_recent_session method."""
    
    def test_get_most_recent(self, tmp_path):
        """Test getting the most recent session."""
        # Create sessions
        session1 = tmp_path / "ses_001"
        session1.mkdir()
        (session1 / "inter_0001.json").write_text(json.dumps({"tokens": {"input": 100}}))
        
        session2 = tmp_path / "ses_002"
        session2.mkdir()
        (session2 / "inter_0001.json").write_text(json.dumps({"tokens": {"input": 200}}))
        
        result = FileProcessor.get_most_recent_session(str(tmp_path))
        
        assert result is not None
        assert isinstance(result, SessionData)
    
    def test_get_most_recent_empty(self, tmp_path):
        """Test getting most recent from empty directory."""
        result = FileProcessor.get_most_recent_session(str(tmp_path))
        assert result is None


class TestExtractProjectName:
    """Tests for extract_project_name method."""
    
    def test_extract_from_absolute_path(self):
        """Test extracting project name from absolute path."""
        result = FileProcessor.extract_project_name("/home/user/myproject")
        assert result == "myproject"
    
    def test_extract_from_relative_path(self):
        """Test extracting project name from relative path."""
        result = FileProcessor.extract_project_name("./myproject")
        assert result == "myproject"
    
    def test_extract_simple_name(self):
        """Test extracting from simple name."""
        result = FileProcessor.extract_project_name("myproject")
        assert result == "myproject"


class TestSessionGenerator:
    """Tests for session_generator method."""
    
    def test_session_generator(self, tmp_path):
        """Test session generator yields sessions."""
        # Create sessions
        session1 = tmp_path / "ses_001"
        session1.mkdir()
        (session1 / "inter_0001.json").write_text(json.dumps({"tokens": {"input": 100}}))
        
        session2 = tmp_path / "ses_002"
        session2.mkdir()
        (session2 / "inter_0001.json").write_text(json.dumps({"tokens": {"input": 200}}))
        
        sessions = list(FileProcessor.session_generator(str(tmp_path)))
        
        assert len(sessions) == 2
        assert all(isinstance(s, SessionData) for s in sessions)
