"""Test configuration and fixtures for OpenCode Monitor."""

import os
import json
import tempfile
from pathlib import Path
import pytest


@pytest.fixture
def temp_directory():
    """Create a temporary directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_config_file(temp_directory):
    """Create a sample configuration file."""
    config_content = """
[paths]
messages_dir = "~/.local/share/opencode/storage/message"
export_dir = "./exports"

[ui]
table_style = "rich"
progress_bars = true
colors = true
live_refresh_interval = 5

[export]
default_format = "csv"
include_metadata = true

[analytics]
default_timeframe = "daily"
recent_sessions_limit = 50
"""
    config_path = temp_directory / "config.toml"
    config_path.write_text(config_content)
    return config_path


@pytest.fixture
def sample_models_file(temp_directory):
    """Create a sample models.json file."""
    models_data = {
        "test-model": {
            "input": 1.0,
            "output": 2.0,
            "cacheWrite": 1.5,
            "cacheRead": 0.1,
            "contextWindow": 128000,
            "sessionQuota": 5.0
        },
        "test-model-free": {
            "input": 0.0,
            "output": 0.0,
            "cacheWrite": 0.0,
            "cacheRead": 0.0,
            "contextWindow": 200000,
            "sessionQuota": 0.0
        }
    }
    models_path = temp_directory / "models.json"
    models_path.write_text(json.dumps(models_data))
    return models_path


@pytest.fixture
def sample_session_json():
    """Return sample session JSON data."""
    return {
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
        "projectPath": "/home/user/myproject",
        "agent": "main"
    }


@pytest.fixture
def sample_pricing_data():
    """Return sample pricing data for testing."""
    return {
        "input": 1.0,
        "output": 2.0,
        "cacheWrite": 1.5,
        "cacheRead": 0.1,
        "contextWindow": 128000,
        "sessionQuota": 5.0
    }


@pytest.fixture
def mock_session_directory(temp_directory):
    """Create a mock session directory structure."""
    sessions_dir = temp_directory / "message"
    sessions_dir.mkdir()
    
    # Create a session with interactions
    session_id = "ses_test123"
    session_dir = sessions_dir / session_id
    session_dir.mkdir()
    
    # Create interaction files
    interaction1 = session_dir / "inter_0001.json"
    interaction1.write_text(json.dumps({
        "modelID": "test-model",
        "tokens": {"input": 1000, "output": 500, "cache": {"write": 200, "read": 100}},
        "timeData": {"created": 1700000000000, "completed": 1700003600000},
        "projectPath": "/home/user/project1",
        "agent": "main"
    }))
    
    interaction2 = session_dir / "inter_0002.json"
    interaction2.write_text(json.dumps({
        "modelID": "test-model",
        "tokens": {"input": 500, "output": 300, "cache": {"write": 100, "read": 50}},
        "timeData": {"created": 1700003700000, "completed": 1700004000000},
        "projectPath": "/home/user/project1",
        "agent": "main"
    }))
    
    return sessions_dir
