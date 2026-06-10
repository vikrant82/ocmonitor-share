"""Tests for session data models."""

import pytest
from pathlib import Path
from decimal import Decimal
from datetime import datetime

from ocmonitor.models.session import TokenUsage, TimeData, InteractionFile, SessionData
from ocmonitor.config import ModelPricing


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


class TestCalculateCost:
    """Tests for InteractionFile.calculate_cost."""

    @pytest.fixture
    def pricing_data(self):
        return {
            "known-model": ModelPricing(
                input=Decimal("1.0"),
                output=Decimal("2.0"),
                cacheWrite=Decimal("1.5"),
                cacheRead=Decimal("0.1"),
                contextWindow=128000,
                sessionQuota=Decimal("5.0"),
            )
        }

    def _make_interaction(self, tmp_path, raw_data=None, model_id="known-model", **tokens):
        f = tmp_path / "inter_0001.json"
        f.write_text("{}")
        return InteractionFile(
            file_path=f,
            session_id="ses_test",
            model_id=model_id,
            tokens=TokenUsage(**tokens) if tokens else TokenUsage(),
            raw_data=raw_data or {},
        )

    def test_uses_stored_cost_when_present(self, tmp_path, pricing_data):
        """OpenCode's pre-computed cost in raw_data is returned directly."""
        interaction = self._make_interaction(
            tmp_path,
            raw_data={"cost": 0.042},
            input=1000000, output=1000000,
        )
        assert interaction.calculate_cost(pricing_data) == Decimal("0.042")

    def test_stored_cost_used_for_model_not_in_local_pricing(self, tmp_path, pricing_data):
        """Models not in local pricing (e.g. OpenRouter) use stored cost instead of returning $0.00."""
        interaction = self._make_interaction(
            tmp_path,
            raw_data={"cost": 0.0173},
            model_id="openrouter/anthropic/claude-opus-4.6",
            input=5000, output=2000,
        )
        assert interaction.calculate_cost(pricing_data) == Decimal("0.0173")

    def test_zero_stored_cost_falls_back_to_local_pricing(self, tmp_path, pricing_data):
        """A stored cost of 0 is treated as 'not computed' and falls back to local pricing."""
        interaction = self._make_interaction(
            tmp_path,
            raw_data={"cost": 0},
            model_id="known-model",
            input=1000000,
        )
        # 1M input tokens at $1.00/1M = $1.00 (from models.json, not stored cost)
        assert interaction.calculate_cost(pricing_data) == Decimal("1.0")

    def test_falls_back_to_local_pricing_when_no_stored_cost(self, tmp_path, pricing_data):
        """When raw_data has no cost, local pricing calculation is used."""
        interaction = self._make_interaction(
            tmp_path,
            model_id="known-model",
            input=1000000,
        )
        # 1M input tokens at $1.00/1M = $1.00
        assert interaction.calculate_cost(pricing_data) == Decimal("1.0")

    def test_force_recalculate_ignores_stored_cost(self, tmp_path, pricing_data):
        """When force_recalculate=True, stored cost is ignored and pricing data is used."""
        interaction = self._make_interaction(
            tmp_path,
            raw_data={"cost": 0.042},
            input=1000000, output=1000000,
        )
        # With default behavior, returns stored cost
        assert interaction.calculate_cost(pricing_data) == Decimal("0.042")
        # With force_recalculate=True, returns calculated cost from pricing data
        # 1M input + 1M output at $1.00 + $2.00 per M = $3.00
        assert interaction.calculate_cost(pricing_data, force_recalculate=True) == Decimal("3.0")

    def test_force_recalculate_uses_current_pricing_for_historical_session(self, tmp_path, pricing_data):
        """force_recalculate=True recomputes costs using current pricing configuration."""
        interaction = self._make_interaction(
            tmp_path,
            raw_data={"cost": 0.042},
            model_id="known-model",
            input=500000, output=500000,
        )
        # Default: uses stored cost
        assert interaction.calculate_cost(pricing_data) == Decimal("0.042")
        # Recalculate: 0.5M input at $1.00/M + 0.5M output at $2.00/M = $1.50
        assert interaction.calculate_cost(pricing_data, force_recalculate=True) == Decimal("1.5")

    def test_force_recalculate_returns_zero_for_unknown_model_without_pricing(self, tmp_path, pricing_data):
        """Unknown models with no pricing return $0.00 when force_recalculate=True."""
        interaction = self._make_interaction(
            tmp_path,
            raw_data={"cost": 0.042},
            model_id="completely-unknown-model-xyz",
            input=1000000, output=1000000,
        )
        # Default: uses stored cost
        assert interaction.calculate_cost(pricing_data) == Decimal("0.042")
        # Recalculate: no pricing found, returns $0.00
        assert interaction.calculate_cost(pricing_data, force_recalculate=True) == Decimal("0.0")


class TestSessionData:
    """Tests for SessionData model."""

    @pytest.fixture
    def pricing_data(self):
        return {
            "known-model": ModelPricing(
                input=Decimal("1.0"),
                output=Decimal("2.0"),
                cacheWrite=Decimal("1.5"),
                cacheRead=Decimal("0.1"),
                contextWindow=128000,
                sessionQuota=Decimal("5.0"),
            )
        }
    
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

    def test_session_total_cost_respects_force_recalculate(self, tmp_path, pricing_data):
        """Session total cost changes when force_recalculate=True for stored cost."""
        session_path = tmp_path / "ses_test"
        session_path.mkdir()

        interaction1 = InteractionFile(
            file_path=session_path / "inter_0001.json",
            session_id="ses_test",
            model_id="known-model",
            tokens=TokenUsage(input=1000000, output=0),
            raw_data={"cost": 0.05},  # Stored cost different from calculated
        )

        interaction2 = InteractionFile(
            file_path=session_path / "inter_0002.json",
            session_id="ses_test",
            model_id="known-model",
            tokens=TokenUsage(input=0, output=1000000),
            raw_data={"cost": 0.10},  # Stored cost different from calculated
        )

        session = SessionData(
            session_id="ses_test",
            session_path=session_path,
            files=[interaction1, interaction2],
        )

        # Default: uses stored costs (0.05 + 0.10 = 0.15)
        assert session.calculate_total_cost(pricing_data) == Decimal("0.15")
        # Recalculate: uses pricing data (1M input at $1/M + 1M output at $2/M = 3.0)
        assert session.calculate_total_cost(pricing_data, force_recalculate=True) == Decimal("3.0")

    def test_session_model_breakdown_respects_force_recalculate(self, tmp_path, pricing_data):
        """Per-model cost totals in session model breakdown change with force_recalculate=True."""
        session_path = tmp_path / "ses_test"
        session_path.mkdir()

        interaction1 = InteractionFile(
            file_path=session_path / "inter_0001.json",
            session_id="ses_test",
            model_id="known-model",
            tokens=TokenUsage(input=1000000, output=0),
            raw_data={"cost": 0.05},  # Stored cost
        )

        interaction2 = InteractionFile(
            file_path=session_path / "inter_0002.json",
            session_id="ses_test",
            model_id="known-model",
            tokens=TokenUsage(input=0, output=1000000),
            raw_data={"cost": 0.10},  # Stored cost
        )

        session = SessionData(
            session_id="ses_test",
            session_path=session_path,
            files=[interaction1, interaction2],
        )

        # Default: uses stored costs
        breakdown = session.get_model_breakdown(pricing_data)
        assert breakdown["known-model"]["cost"] == Decimal("0.15")

        # Recalculate: uses pricing data
        breakdown_recalc = session.get_model_breakdown(pricing_data, force_recalculate=True)
        assert breakdown_recalc["known-model"]["cost"] == Decimal("3.0")


class TestAnalyticsForceRecalculate:
    """Tests for force_recalculate in analytics models (DailyUsage, WeeklyUsage, MonthlyUsage)."""

    @pytest.fixture
    def pricing_data(self):
        return {
            "known-model": ModelPricing(
                input=Decimal("1.0"),
                output=Decimal("2.0"),
                cacheWrite=Decimal("1.5"),
                cacheRead=Decimal("0.1"),
                contextWindow=128000,
                sessionQuota=Decimal("5.0"),
            )
        }

    def _make_interaction(self, tmp_path, session_id="ses_test", raw_data=None, model_id="known-model", **tokens):
        f = tmp_path / f"{session_id}_inter.json"
        f.write_text("{}")
        return InteractionFile(
            file_path=f,
            session_id=session_id,
            model_id=model_id,
            tokens=TokenUsage(**tokens) if tokens else TokenUsage(),
            raw_data=raw_data or {},
        )

    def _make_session(self, tmp_path, session_id="ses_test", raw_data=None, model_id="known-model", **tokens):
        session_path = tmp_path / session_id
        session_path.mkdir(exist_ok=True)
        interaction = self._make_interaction(
            tmp_path, session_id, raw_data, model_id, **tokens
        )
        return SessionData(
            session_id=session_id,
            session_path=session_path,
            files=[interaction],
        )

    def test_daily_usage_total_cost_respects_force_recalculate(self, tmp_path, pricing_data):
        """DailyUsage.calculate_total_cost changes with force_recalculate=True."""
        from ocmonitor.models.analytics import DailyUsage
        from datetime import date

        session = self._make_session(
            tmp_path,
            session_id="ses_1",
            raw_data={"cost": 0.50},
            input=1000000,
            output=1000000,
        )

        daily = DailyUsage(date=date(2026, 4, 7), sessions=[session])

        # Default: uses stored cost
        assert daily.calculate_total_cost(pricing_data) == Decimal("0.50")
        # Recalculate: 1M input at $1/M + 1M output at $2/M = $3.00
        assert daily.calculate_total_cost(pricing_data, force_recalculate=True) == Decimal("3.0")

    def test_weekly_usage_total_cost_respects_force_recalculate(self, tmp_path, pricing_data):
        """WeeklyUsage.calculate_total_cost changes with force_recalculate=True."""
        from ocmonitor.models.analytics import DailyUsage, WeeklyUsage
        from datetime import date

        session = self._make_session(
            tmp_path,
            session_id="ses_1",
            raw_data={"cost": 0.50},
            input=1000000,
            output=1000000,
        )

        daily = DailyUsage(date=date(2026, 4, 7), sessions=[session])
        weekly = WeeklyUsage(
            year=2026, week=15, start_date=date(2026, 4, 6), end_date=date(2026, 4, 12),
            daily_usage=[daily],
        )

        # Default: uses stored cost
        assert weekly.calculate_total_cost(pricing_data) == Decimal("0.50")
        # Recalculate: $3.00
        assert weekly.calculate_total_cost(pricing_data, force_recalculate=True) == Decimal("3.0")

    def test_monthly_usage_total_cost_respects_force_recalculate(self, tmp_path, pricing_data):
        """MonthlyUsage.calculate_total_cost changes with force_recalculate=True."""
        from ocmonitor.models.analytics import DailyUsage, WeeklyUsage, MonthlyUsage
        from datetime import date

        session = self._make_session(
            tmp_path,
            session_id="ses_1",
            raw_data={"cost": 0.50},
            input=1000000,
            output=1000000,
        )

        daily = DailyUsage(date=date(2026, 4, 7), sessions=[session])
        weekly = WeeklyUsage(
            year=2026, week=15, start_date=date(2026, 4, 6), end_date=date(2026, 4, 12),
            daily_usage=[daily],
        )
        monthly = MonthlyUsage(year=2026, month=4, weekly_usage=[weekly])

        # Default: uses stored cost
        assert monthly.calculate_total_cost(pricing_data) == Decimal("0.50")
        # Recalculate: $3.00
        assert monthly.calculate_total_cost(pricing_data, force_recalculate=True) == Decimal("3.0")

    def test_create_model_breakdown_respects_force_recalculate(self, tmp_path, pricing_data):
        """TimeframeAnalyzer.create_model_breakdown changes with force_recalculate=True."""
        from ocmonitor.models.analytics import TimeframeAnalyzer

        session = self._make_session(
            tmp_path,
            session_id="ses_1",
            raw_data={"cost": 0.50},
            input=1000000,
            output=1000000,
        )

        # Default: uses stored cost
        report = TimeframeAnalyzer.create_model_breakdown([session], pricing_data)
        assert report.total_cost == Decimal("0.50")

        # Recalculate: $3.00
        report_recalc = TimeframeAnalyzer.create_model_breakdown(
            [session], pricing_data, force_recalculate=True
        )
        assert report_recalc.total_cost == Decimal("3.0")

    def test_create_project_breakdown_respects_force_recalculate(self, tmp_path, pricing_data):
        """TimeframeAnalyzer.create_project_breakdown changes with force_recalculate=True."""
        from ocmonitor.models.analytics import TimeframeAnalyzer

        session = self._make_session(
            tmp_path,
            session_id="ses_1",
            raw_data={"cost": 0.50},
            input=1000000,
            output=1000000,
        )

        # Default: uses stored cost
        report = TimeframeAnalyzer.create_project_breakdown([session], pricing_data)
        assert report.total_cost == Decimal("0.50")

        # Recalculate: $3.00
        report_recalc = TimeframeAnalyzer.create_project_breakdown(
            [session], pricing_data, force_recalculate=True
        )
        assert report_recalc.total_cost == Decimal("3.0")


class TestWorkflowForceRecalculate:
    """Tests for force_recalculate in SessionWorkflow model."""

    @pytest.fixture
    def pricing_data(self):
        return {
            "known-model": ModelPricing(
                input=Decimal("1.0"),
                output=Decimal("2.0"),
                cacheWrite=Decimal("1.5"),
                cacheRead=Decimal("0.1"),
                contextWindow=128000,
                sessionQuota=Decimal("5.0"),
            )
        }

    def _make_session(self, tmp_path, session_id="ses_test", raw_data=None, model_id="known-model", **tokens):
        session_path = tmp_path / session_id
        session_path.mkdir(exist_ok=True)
        f = tmp_path / f"{session_id}_inter.json"
        f.write_text("{}")
        interaction = InteractionFile(
            file_path=f,
            session_id=session_id,
            model_id=model_id,
            tokens=TokenUsage(**tokens) if tokens else TokenUsage(),
            raw_data=raw_data or {},
        )
        return SessionData(
            session_id=session_id,
            session_path=session_path,
            files=[interaction],
        )

    def test_workflow_total_cost_respects_force_recalculate(self, tmp_path, pricing_data):
        """SessionWorkflow.calculate_total_cost changes with force_recalculate=True."""
        from ocmonitor.models.workflow import SessionWorkflow

        main_session = self._make_session(
            tmp_path,
            session_id="ses_main",
            raw_data={"cost": 0.50},
            input=1000000,
            output=1000000,
        )

        sub_session = self._make_session(
            tmp_path,
            session_id="ses_sub",
            raw_data={"cost": 0.25},
            input=500000,
            output=500000,
        )

        workflow = SessionWorkflow(
            workflow_id="ses_main",
            main_session=main_session,
            sub_agent_sessions=[sub_session],
        )

        # Default: uses stored costs (0.50 + 0.25 = 0.75)
        assert workflow.calculate_total_cost(pricing_data) == Decimal("0.75")

        # Recalculate: (1M input + 1M output at $3/M) + (0.5M input + 0.5M output at $3/M)
        # = $3.00 + $1.50 = $4.50
        assert workflow.calculate_total_cost(pricing_data, force_recalculate=True) == Decimal("4.5")


class TestReportGeneratorModelBreakdown:
    """Tests for ReportGenerator._get_model_breakdown_for_sessions provider-aware grouping."""

    def _make_file(self, tmp_path, session_id, name, model_id, provider_id=None, **tokens):
        f = tmp_path / f"{name}.json"
        f.write_text("{}")
        return InteractionFile(
            file_path=f,
            session_id=session_id,
            model_id=model_id,
            provider_id=provider_id,
            tokens=TokenUsage(**tokens) if tokens else TokenUsage(),
            raw_data={},
        )

    def test_same_model_id_different_providers_are_not_merged(self, tmp_path):
        """Two providers using the same model_id must produce two separate breakdown rows."""
        from unittest.mock import MagicMock
        from ocmonitor.services.report_generator import ReportGenerator

        file_a = self._make_file(
            tmp_path, "ses1", "file_a", model_id="claude-sonnet", provider_id="prov-a",
            input=100, output=50,
        )
        file_b = self._make_file(
            tmp_path, "ses1", "file_b", model_id="claude-sonnet", provider_id="prov-b",
            input=200, output=80,
        )

        session = SessionData(
            session_id="ses1",
            session_path=tmp_path / "ses1",
            files=[file_a, file_b],
        )

        analyzer = MagicMock()
        analyzer.pricing_data = {}
        rg = ReportGenerator(analyzer=analyzer)

        results = rg._get_model_breakdown_for_sessions([session])

        models_in_results = {r["model"] for r in results}
        assert "prov-a/claude-sonnet" in models_in_results, "prov-a entry missing"
        assert "prov-b/claude-sonnet" in models_in_results, "prov-b entry missing"
        assert len(results) == 2, f"Expected 2 rows, got {len(results)}: {models_in_results}"

    def test_same_provider_same_model_id_are_merged(self, tmp_path):
        """Two files with the same provider+model_id must be aggregated into one row."""
        from unittest.mock import MagicMock
        from ocmonitor.services.report_generator import ReportGenerator

        file_a = self._make_file(
            tmp_path, "ses1", "file_c", model_id="gpt-4o", provider_id="openai",
            input=100, output=50,
        )
        file_b = self._make_file(
            tmp_path, "ses1", "file_d", model_id="gpt-4o", provider_id="openai",
            input=200, output=80,
        )

        session = SessionData(
            session_id="ses1",
            session_path=tmp_path / "ses1",
            files=[file_a, file_b],
        )

        analyzer = MagicMock()
        analyzer.pricing_data = {}
        rg = ReportGenerator(analyzer=analyzer)

        results = rg._get_model_breakdown_for_sessions([session])

        assert len(results) == 1
        assert results[0]["model"] == "openai/gpt-4o"
        assert results[0]["interactions"] == 2
        assert results[0]["input_tokens"] == 300
        assert results[0]["output_tokens"] == 130
