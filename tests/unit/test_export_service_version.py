"""Unit tests for export metadata version reporting."""

import json
from decimal import Decimal
from pathlib import Path

from ocmonitor.models.analytics import ModelBreakdownReport, ModelUsageStats
import ocmonitor.services.export_service as export_module
from ocmonitor.services.export_service import ExportService


class TestExportServiceVersion:
    """Tests for export version metadata."""

    def test_export_json_uses_resolved_version(self, tmp_path, monkeypatch):
        monkeypatch.setattr(export_module, "get_version", lambda: "9.9.9")

        service = ExportService(export_dir=str(tmp_path))
        output_path = service.export_to_json(
            data=[{"report": "sessions"}],
            filename="version_test",
            include_metadata=True,
        )

        exported = json.loads(Path(output_path).read_text(encoding="utf-8"))
        assert exported["metadata"]["export_info"]["version"] == "9.9.9"


class TestExportModelsBreakdown:
    """Regression tests for model breakdown export field mapping."""

    def test_models_export_maps_display_model_to_model_name_column(self, tmp_path):
        """_extract_export_data('models') emits model_name from display_model."""
        service = ExportService(export_dir=str(tmp_path))
        report_data = {
            "model_breakdown": ModelBreakdownReport(
                timeframe="all",
                model_stats=[
                    ModelUsageStats(
                        display_model="claude-sonnet-4.5",
                        total_sessions=1,
                        total_interactions=2,
                        total_cost=Decimal("0.01"),
                    )
                ],
            )
        }

        rows = service._extract_export_data(report_data, "models")

        assert len(rows) == 1
        assert rows[0]["model_name"] == "claude-sonnet-4.5"
