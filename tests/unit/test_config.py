"""Tests for configuration management."""

import os
import json
import pytest
from pathlib import Path
from decimal import Decimal

from ocmonitor.config import (
    PathsConfig,
    UIConfig,
    ExportConfig,
    ModelsConfig,
    AnalyticsConfig,
    Config,
    ModelPricing,
    ConfigManager,
    opencode_storage_path,
)


class TestOpencodeStoragePath:
    """Tests for opencode_storage_path utility function."""
    
    def test_default_path(self):
        """Test default storage path generation."""
        path = opencode_storage_path()
        assert "opencode/storage" in path
        assert "~/.local/share" in path or "XDG_DATA_HOME" in os.environ
    
    def test_path_with_subdirectory(self):
        """Test path generation with subdirectory."""
        path = opencode_storage_path("message")
        assert "opencode/storage/message" in path
    
    def test_xdg_data_home_respected(self, monkeypatch):
        """Test that XDG_DATA_HOME environment variable is respected."""
        monkeypatch.setenv("XDG_DATA_HOME", "/custom/data")
        path = opencode_storage_path()
        assert path.startswith("/custom/data")


class TestPathsConfig:
    """Tests for PathsConfig model."""
    
    def test_default_values(self):
        """Test default path configuration values."""
        config = PathsConfig()
        assert "message" in config.messages_dir
        assert "opencode/storage" in config.opencode_storage_dir
        assert config.export_dir == "./exports"
    
    def test_path_expansion(self):
        """Test that user paths are expanded."""
        config = PathsConfig(messages_dir="~/test/messages")
        assert not config.messages_dir.startswith("~")
        assert config.messages_dir.endswith("test/messages")
    
    def test_environment_variable_expansion(self, monkeypatch):
        """Test that environment variables in paths are expanded."""
        monkeypatch.setenv("TEST_DIR", "/test/path")
        config = PathsConfig(messages_dir="$TEST_DIR/messages")
        assert "/test/path/messages" in config.messages_dir


class TestUIConfig:
    """Tests for UIConfig model."""
    
    def test_default_values(self):
        """Test default UI configuration values."""
        config = UIConfig()
        assert config.table_style == "rich"
        assert config.progress_bars is True
        assert config.colors is True
        assert config.live_refresh_interval == 5
    
    def test_valid_table_styles(self):
        """Test that valid table styles are accepted."""
        for style in ["rich", "simple", "minimal"]:
            config = UIConfig(table_style=style)
            assert config.table_style == style
    
    def test_invalid_table_style(self):
        """Test that invalid table styles are rejected."""
        with pytest.raises(ValueError):
            UIConfig(table_style="invalid")
    
    def test_live_refresh_interval_bounds(self):
        """Test live refresh interval boundary values."""
        # Valid bounds
        config = UIConfig(live_refresh_interval=1)
        assert config.live_refresh_interval == 1
        
        config = UIConfig(live_refresh_interval=60)
        assert config.live_refresh_interval == 60
        
        # Invalid bounds
        with pytest.raises(ValueError):
            UIConfig(live_refresh_interval=0)
        
        with pytest.raises(ValueError):
            UIConfig(live_refresh_interval=61)


class TestExportConfig:
    """Tests for ExportConfig model."""
    
    def test_default_values(self):
        """Test default export configuration values."""
        config = ExportConfig()
        assert config.default_format == "csv"
        assert config.include_metadata is True
        assert config.include_raw_data is False
    
    def test_valid_formats(self):
        """Test that valid export formats are accepted."""
        for fmt in ["csv", "json"]:
            config = ExportConfig(default_format=fmt)
            assert config.default_format == fmt
    
    def test_invalid_format(self):
        """Test that invalid export formats are rejected."""
        with pytest.raises(ValueError):
            ExportConfig(default_format="xml")


class TestAnalyticsConfig:
    """Tests for AnalyticsConfig model."""
    
    def test_default_values(self):
        """Test default analytics configuration values."""
        config = AnalyticsConfig()
        assert config.default_timeframe == "daily"
        assert config.recent_sessions_limit == 50
    
    def test_valid_timeframes(self):
        """Test that valid timeframes are accepted."""
        for tf in ["daily", "weekly", "monthly"]:
            config = AnalyticsConfig(default_timeframe=tf)
            assert config.default_timeframe == tf
    
    def test_recent_sessions_limit_bounds(self):
        """Test recent sessions limit boundary values."""
        # Valid bounds
        config = AnalyticsConfig(recent_sessions_limit=1)
        assert config.recent_sessions_limit == 1
        
        config = AnalyticsConfig(recent_sessions_limit=1000)
        assert config.recent_sessions_limit == 1000
        
        # Invalid bounds
        with pytest.raises(ValueError):
            AnalyticsConfig(recent_sessions_limit=0)
        
        with pytest.raises(ValueError):
            AnalyticsConfig(recent_sessions_limit=1001)


class TestModelPricing:
    """Tests for ModelPricing model."""
    
    def test_pricing_with_aliases(self):
        """Test that pricing data with alias fields is loaded correctly."""
        pricing_data = {
            "input": 3.0,
            "output": 15.0,
            "cacheWrite": 3.75,
            "cacheRead": 0.3,
            "contextWindow": 200000,
            "sessionQuota": 6.0
        }
        
        pricing = ModelPricing(**pricing_data)
        assert pricing.input == Decimal("3.0")
        assert pricing.output == Decimal("15.0")
        assert pricing.cache_write == Decimal("3.75")
        assert pricing.cache_read == Decimal("0.3")
        assert pricing.context_window == 200000
        assert pricing.session_quota == Decimal("6.0")


class TestConfigManager:
    """Tests for ConfigManager class."""
    
    def test_init_without_path(self):
        """Test initialization without explicit config path."""
        manager = ConfigManager()
        # Should find default path
        assert manager.config_path is not None
    
    def test_init_with_path(self, temp_directory):
        """Test initialization with explicit config path."""
        config_path = temp_directory / "test_config.toml"
        config_path.write_text("")
        manager = ConfigManager(config_path=str(config_path))
        assert manager.config_path == str(config_path)
    
    def test_load_default_config(self):
        """Test loading default configuration when file doesn't exist."""
        manager = ConfigManager(config_path="/nonexistent/path/config.toml")
        config = manager.config
        
        assert isinstance(config, Config)
        assert config.ui.table_style == "rich"
        assert config.export.default_format == "csv"
    
    def test_load_config_from_file(self, sample_config_file):
        """Test loading configuration from file."""
        manager = ConfigManager(config_path=str(sample_config_file))
        config = manager.config
        
        assert isinstance(config, Config)
        assert config.ui.table_style == "rich"
        assert config.export.default_format == "csv"
        assert config.analytics.recent_sessions_limit == 50
    
    def test_lazy_loading(self, sample_config_file):
        """Test that configuration is loaded lazily."""
        manager = ConfigManager(config_path=str(sample_config_file))
        assert manager._config is None
        
        # Access config
        _ = manager.config
        assert manager._config is not None
    
    def test_reload_config(self, sample_config_file):
        """Test reloading configuration."""
        manager = ConfigManager(config_path=str(sample_config_file))
        
        # Load config
        config1 = manager.config
        
        # Reload
        manager.reload()
        config2 = manager.config
        
        # Should be new instances
        assert config1 is not config2
    
    def test_load_pricing_data(self, temp_directory):
        """Test loading pricing data from JSON file."""
        # Create config with models.json
        models_data = {
            "test-model": {
                "input": 1.0,
                "output": 2.0,
                "cacheWrite": 1.5,
                "cacheRead": 0.1,
                "contextWindow": 128000,
                "sessionQuota": 5.0
            }
        }
        
        models_file = temp_directory / "models.json"
        models_file.write_text(json.dumps(models_data))
        
        config_file = temp_directory / "config.toml"
        config_file.write_text(f"""
[models]
config_file = "{models_file}"
""")
        
        manager = ConfigManager(config_path=str(config_file))
        pricing = manager.load_pricing_data()
        
        assert "test-model" in pricing
        assert pricing["test-model"].input == Decimal("1.0")
    
    def test_load_pricing_data_missing_file(self, temp_directory):
        """Test loading pricing data when file doesn't exist."""
        config_file = temp_directory / "config.toml"
        config_file.write_text("""
[models]
config_file = "/nonexistent/path/models.json"
""")
        
        manager = ConfigManager(config_path=str(config_file))
        pricing = manager.load_pricing_data()
        
        # Falls back to default models.json in package directory
        assert len(pricing) > 0  # Should have default models
    
    def test_get_model_pricing(self, temp_directory):
        """Test getting pricing for specific model."""
        models_data = {
            "claude-sonnet-4": {
                "input": 3.0,
                "output": 15.0,
                "cacheWrite": 3.75,
                "cacheRead": 0.3,
                "contextWindow": 200000,
                "sessionQuota": 6.0
            }
        }
        
        models_file = temp_directory / "models.json"
        models_file.write_text(json.dumps(models_data))
        
        config_file = temp_directory / "config.toml"
        config_file.write_text(f"""
[models]
config_file = "{models_file}"
""")
        
        manager = ConfigManager(config_path=str(config_file))
        pricing = manager.get_model_pricing("claude-sonnet-4")
        
        assert pricing is not None
        assert pricing.input == Decimal("3.0")
        
        # Test non-existent model
        assert manager.get_model_pricing("non-existent") is None
    
    def test_invalid_config_file(self, temp_directory):
        """Test handling of invalid config file."""
        config_file = temp_directory / "invalid_config.toml"
        config_file.write_text("invalid toml content [[[")
        
        manager = ConfigManager(config_path=str(config_file))
        
        with pytest.raises(ValueError) as exc_info:
            _ = manager.config
        
        assert "Invalid configuration file" in str(exc_info.value)
