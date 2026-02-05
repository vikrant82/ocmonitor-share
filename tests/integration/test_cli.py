"""Integration tests for CLI commands."""

import os
import json
import pytest
from pathlib import Path
from click.testing import CliRunner

from ocmonitor.cli import cli


@pytest.fixture
def mock_sessions_dir(tmp_path):
    """Create a mock sessions directory with test data."""
    sessions_dir = tmp_path / "message"
    sessions_dir.mkdir()
    
    # Create session 1
    session1 = sessions_dir / "ses_test1"
    session1.mkdir()
    
    inter1 = session1 / "inter_0001.json"
    inter1.write_text(json.dumps({
        "modelID": "test-model",
        "tokens": {"input": 1000, "output": 500, "cache": {"write": 100, "read": 50}},
        "timeData": {"created": 1700000000000, "completed": 1700003600000},
        "projectPath": "/home/user/project1",
        "agent": "main"
    }))
    
    # Create session 2
    session2 = sessions_dir / "ses_test2"
    session2.mkdir()
    
    inter2 = session2 / "inter_0001.json"
    inter2.write_text(json.dumps({
        "modelID": "test-model",
        "tokens": {"input": 2000, "output": 1000, "cache": {"write": 200, "read": 100}},
        "timeData": {"created": 1700003700000, "completed": 1700004000000},
        "projectPath": "/home/user/project2",
        "agent": "explore"
    }))
    
    return sessions_dir


class TestConfigCommand:
    """Tests for config CLI commands."""
    
    def test_config_show(self):
        """Test config show command."""
        runner = CliRunner()
        result = runner.invoke(cli, ['config', 'show'])
        
        # Should succeed and show configuration
        assert result.exit_code == 0
        assert result.output != ""


class TestSessionsCommand:
    """Tests for sessions CLI command."""
    
    def test_sessions_basic(self, mock_sessions_dir):
        """Test basic sessions command."""
        runner = CliRunner()
        result = runner.invoke(cli, ['sessions', str(mock_sessions_dir)])
        
        # Should succeed
        assert result.exit_code == 0
    
    def test_sessions_with_limit(self, mock_sessions_dir):
        """Test sessions command with limit."""
        runner = CliRunner()
        result = runner.invoke(cli, ['sessions', str(mock_sessions_dir), '--limit', '1'])
        
        assert result.exit_code == 0
    
    def test_sessions_nonexistent_directory(self):
        """Test sessions command with non-existent directory."""
        runner = CliRunner()
        result = runner.invoke(cli, ['sessions', '/nonexistent/path'])
        
        # Should handle gracefully - may succeed with no output or show error
        assert result.exit_code in [0, 2]


class TestDailyCommand:
    """Tests for daily CLI command."""
    
    def test_daily_basic(self, mock_sessions_dir):
        """Test basic daily command."""
        runner = CliRunner()
        result = runner.invoke(cli, ['daily', str(mock_sessions_dir)])
        
        # Should succeed
        assert result.exit_code == 0
    
    def test_daily_with_breakdown(self, mock_sessions_dir):
        """Test daily command with breakdown flag."""
        runner = CliRunner()
        result = runner.invoke(cli, ['daily', str(mock_sessions_dir), '--breakdown'])
        
        assert result.exit_code == 0


class TestWeeklyCommand:
    """Tests for weekly CLI command."""
    
    def test_weekly_basic(self, mock_sessions_dir):
        """Test basic weekly command."""
        runner = CliRunner()
        result = runner.invoke(cli, ['weekly', str(mock_sessions_dir)])
        
        assert result.exit_code == 0
    
    def test_weekly_with_start_day(self, mock_sessions_dir):
        """Test weekly command with custom start day."""
        runner = CliRunner()
        result = runner.invoke(cli, ['weekly', str(mock_sessions_dir), '--start-day', 'sunday'])
        
        assert result.exit_code == 0


class TestMonthlyCommand:
    """Tests for monthly CLI command."""
    
    def test_monthly_basic(self, mock_sessions_dir):
        """Test basic monthly command."""
        runner = CliRunner()
        result = runner.invoke(cli, ['monthly', str(mock_sessions_dir)])
        
        assert result.exit_code == 0


class TestExportCommand:
    """Tests for export CLI command."""
    
    def test_export_csv(self, mock_sessions_dir, tmp_path):
        """Test export command with CSV format."""
        export_dir = tmp_path / "exports"
        export_dir.mkdir()
        
        runner = CliRunner()
        result = runner.invoke(cli, [
            'export', 'sessions', str(mock_sessions_dir),
            '--format', 'csv'
        ])
        
        # Should succeed or handle missing options gracefully
        assert result.exit_code in [0, 2]
    
    def test_export_json(self, mock_sessions_dir, tmp_path):
        """Test export command with JSON format."""
        export_dir = tmp_path / "exports"
        export_dir.mkdir()
        
        runner = CliRunner()
        result = runner.invoke(cli, [
            'export', 'sessions', str(mock_sessions_dir),
            '--format', 'json'
        ])
        
        assert result.exit_code in [0, 2]


class TestSessionCommand:
    """Tests for single session CLI command."""
    
    def test_session_single(self, mock_sessions_dir):
        """Test analyzing single session."""
        session_dir = mock_sessions_dir / "ses_test1"
        
        runner = CliRunner()
        result = runner.invoke(cli, ['session', str(session_dir)])
        
        assert result.exit_code == 0


class TestCLIHelp:
    """Tests for CLI help functionality."""
    
    def test_main_help(self):
        """Test main CLI help."""
        runner = CliRunner()
        result = runner.invoke(cli, ['--help'])
        
        assert result.exit_code == 0
        assert "Usage:" in result.output
    
    def test_sessions_help(self):
        """Test sessions command help."""
        runner = CliRunner()
        result = runner.invoke(cli, ['sessions', '--help'])
        
        assert result.exit_code == 0
        assert "Usage:" in result.output
    
    def test_daily_help(self):
        """Test daily command help."""
        runner = CliRunner()
        result = runner.invoke(cli, ['daily', '--help'])
        
        assert result.exit_code == 0
        assert "Usage:" in result.output
    
    def test_export_help(self):
        """Test export command help."""
        runner = CliRunner()
        result = runner.invoke(cli, ['export', '--help'])
        
        assert result.exit_code == 0
        assert "Usage:" in result.output
    
    def test_config_help(self):
        """Test config command help."""
        runner = CliRunner()
        result = runner.invoke(cli, ['config', '--help'])
        
        assert result.exit_code == 0
        assert "Usage:" in result.output
