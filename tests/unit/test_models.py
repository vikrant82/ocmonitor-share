"""Tests for session data models."""

import pytest
from pathlib import Path
from decimal import Decimal
from datetime import datetime

from ocmonitor.models.session import TokenUsage, TimeData, InteractionFile, SessionData


class TestTokenUsage:
    """Tests for TokenUsage model."""
    
    def test_default_values(self):
        """Test default token usage values."""
        tokens = TokenUsage()
        assert tokens.input == 0
        assert tokens.output == 0
        assert tokens.cache_write == 0
        assert tokens.cache_read == 0
    
    def test_total_calculation(self):
        """Test total token calculation."""
        tokens = TokenUsage(input=1000, output=500, cache_write=200, cache_read=100)
        assert tokens.total == 1800
    
    def test_negative_values_rejected(self):
        """Test that negative token values are rejected."""
        with pytest.raises(ValueError):
            TokenUsage(input=-1)
    
    def test_zero_values_allowed(self):
        """Test that zero values are allowed."""
        tokens = TokenUsage(input=0, output=0, cache_write=0, cache_read=0)
        assert tokens.total == 0


class TestTimeData:
    """Tests for TimeData model."""
    
    def test_duration_calculation(self):
        """Test duration calculation from timestamps."""
        time_data = TimeData(created=1000, completed=5000)
        assert time_data.duration_ms == 4000
    
    def test_duration_none_when_missing_created(self):
        """Test that duration is None when created is missing."""
        time_data = TimeData(completed=5000)
        assert time_data.duration_ms is None
    
    def test_duration_none_when_missing_completed(self):
        """Test that duration is None when completed is missing."""
        time_data = TimeData(created=1000)
        assert time_data.duration_ms is None
    
    def test_created_datetime_conversion(self):
        """Test created timestamp to datetime conversion."""
        # Unix timestamp for 2024-01-01 00:00:00 UTC
        timestamp_ms = 1704067200000
        time_data = TimeData(created=timestamp_ms)
        
        dt = time_data.created_datetime
        assert dt is not None
        assert dt.year == 2024
        assert dt.month == 1
        assert dt.day == 1
    
    def test_datetime_none_when_timestamp_missing(self):
        """Test that datetime is None when timestamp is missing."""
        time_data = TimeData()
        assert time_data.created_datetime is None
        assert time_data.completed_datetime is None


class TestInteractionFile:
    """Tests for InteractionFile model."""
    
    def test_default_values(self):
        """Test default interaction file values."""
        file_path = Path("/tmp/test.json")
        interaction = InteractionFile(file_path=file_path, session_id="ses_test")
        
        assert interaction.model_id == "unknown"
        assert interaction.tokens.total == 0
        assert interaction.time_data is None
        assert interaction.project_path is None
    
    def test_file_path_validation_string(self):
        """Test that string file paths are converted to Path objects."""
        interaction = InteractionFile(
            file_path="/tmp/test.json",
            session_id="ses_test"
        )
        assert isinstance(interaction.file_path, Path)
    
    def test_file_name_computed(self, tmp_path):
        """Test that file name is computed correctly."""
        test_file = tmp_path / "interaction.json"
        test_file.write_text("{}")
        
        interaction = InteractionFile(file_path=test_file, session_id="ses_test")
        assert interaction.file_name == "interaction.json"
    
    def test_project_name_with_path(self):
        """Test project name extraction from project path."""
        interaction = InteractionFile(
            file_path=Path("/tmp/test.json"),
            session_id="ses_test",
            project_path="/home/user/myproject"
        )
        assert interaction.project_name == "myproject"
    
    def test_project_name_unknown(self):
        """Test project name is 'Unknown' when project path is None."""
        interaction = InteractionFile(
            file_path=Path("/tmp/test.json"),
            session_id="ses_test",
            project_path=None
        )
        assert interaction.project_name == "Unknown"


class TestSessionData:
    """Tests for SessionData model."""
    
    def test_session_data_creation(self, tmp_path):
        """Test basic session data creation."""
        session_path = tmp_path / "ses_test"
        session_path.mkdir()
        
        interaction = InteractionFile(
            file_path=session_path / "inter_0001.json",
            session_id="ses_test",
            model_id="test-model",
            tokens=TokenUsage(input=1000, output=500)
        )
        
        session = SessionData(
            session_id="ses_test",
            session_path=session_path,
            files=[interaction],
            session_title="Test Session"
        )
        
        assert session.session_id == "ses_test"
        assert session.session_title == "Test Session"
        assert len(session.files) == 1
    
    def test_total_tokens_aggregation(self, tmp_path):
        """Test that total tokens are aggregated across all interactions."""
        session_path = tmp_path / "ses_test"
        session_path.mkdir()
        
        interaction1 = InteractionFile(
            file_path=session_path / "inter_0001.json",
            session_id="ses_test",
            tokens=TokenUsage(input=1000, output=500, cache_write=200, cache_read=100)
        )
        
        interaction2 = InteractionFile(
            file_path=session_path / "inter_0002.json",
            session_id="ses_test",
            tokens=TokenUsage(input=500, output=300, cache_write=100, cache_read=50)
        )
        
        session = SessionData(
            session_id="ses_test",
            session_path=session_path,
            files=[interaction1, interaction2]
        )
        
        assert session.total_tokens.input == 1500
        assert session.total_tokens.output == 800
        assert session.total_tokens.cache_write == 300
        assert session.total_tokens.cache_read == 150
        assert session.total_tokens.total == 2750
    
    def test_session_path_validation_string(self, tmp_path):
        """Test that string session paths are converted to Path objects."""
        session_path = tmp_path / "ses_test"
        session_path.mkdir()
        
        session = SessionData(
            session_id="ses_test",
            session_path=str(session_path),
            files=[]
        )
        
        assert isinstance(session.session_path, Path)
    
    def test_models_used_computed(self, tmp_path):
        """Test that models_used returns unique model IDs."""
        session_path = tmp_path / "ses_test"
        session_path.mkdir()
        
        interaction1 = InteractionFile(
            file_path=session_path / "inter_0001.json",
            session_id="ses_test",
            model_id="model-a"
        )
        
        interaction2 = InteractionFile(
            file_path=session_path / "inter_0002.json",
            session_id="ses_test",
            model_id="model-b"
        )
        
        interaction3 = InteractionFile(
            file_path=session_path / "inter_0003.json",
            session_id="ses_test",
            model_id="model-a"  # Duplicate
        )
        
        session = SessionData(
            session_id="ses_test",
            session_path=session_path,
            files=[interaction1, interaction2, interaction3]
        )
        
        models = session.models_used
        assert "model-a" in models
        assert "model-b" in models
        assert len(models) == 2  # Should only have 2 unique models
