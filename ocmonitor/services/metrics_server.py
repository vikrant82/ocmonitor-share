"""Prometheus metrics server for OpenCode Monitor."""

import logging
import threading
from typing import Dict

from prometheus_client import start_http_server
from prometheus_client.core import CollectorRegistry, GaugeMetricFamily

from ..config import ModelPricing
from ..models.analytics import TimeframeAnalyzer
from ..services.session_analyzer import SessionAnalyzer

logger = logging.getLogger(__name__)


class OCMonitorCollector:
    """Custom Prometheus collector that loads fresh data on each scrape."""

    def __init__(self, pricing_data: Dict[str, ModelPricing]):
        """Initialize the collector with pricing data and a session analyzer."""
        self._analyzer = SessionAnalyzer(pricing_data)
        self._pricing_data = pricing_data

    def describe(self):
        """Return empty list; metrics are described in collect()."""
        return []

    def collect(self):
        """Yield GaugeMetricFamily objects with current session data."""
        try:
            sessions = self._analyzer.analyze_all_sessions()

            model_report = TimeframeAnalyzer.create_model_breakdown(
                sessions, self._pricing_data
            )
            project_report = TimeframeAnalyzer.create_project_breakdown(
                sessions, self._pricing_data
            )

            total_duration_hours = sum(s.duration_hours for s in sessions)

            # --- Per-model metrics ---
            tokens_input = GaugeMetricFamily(
                "ocmonitor_tokens_input_total",
                "Total input tokens",
                labels=["model"],
            )
            tokens_output = GaugeMetricFamily(
                "ocmonitor_tokens_output_total",
                "Total output tokens",
                labels=["model"],
            )
            tokens_cache_read = GaugeMetricFamily(
                "ocmonitor_tokens_cache_read_total",
                "Total cache read tokens",
                labels=["model"],
            )
            tokens_cache_write = GaugeMetricFamily(
                "ocmonitor_tokens_cache_write_total",
                "Total cache write tokens",
                labels=["model"],
            )
            cost = GaugeMetricFamily(
                "ocmonitor_cost_dollars_total",
                "Total cost in USD",
                labels=["model"],
            )
            sessions_total = GaugeMetricFamily(
                "ocmonitor_sessions_total",
                "Total number of sessions",
                labels=["model"],
            )
            interactions_total = GaugeMetricFamily(
                "ocmonitor_interactions_total",
                "Total number of interactions",
                labels=["model"],
            )
            output_rate = GaugeMetricFamily(
                "ocmonitor_output_rate_tokens_per_second",
                "Median output tokens per second",
                labels=["model"],
            )

            for model_stats in model_report.model_stats:
                label = [model_stats.display_model]
                tokens_input.add_metric(label, model_stats.total_tokens.input)
                tokens_output.add_metric(label, model_stats.total_tokens.output)
                tokens_cache_read.add_metric(label, model_stats.total_tokens.cache_read)
                tokens_cache_write.add_metric(label, model_stats.total_tokens.cache_write)
                cost.add_metric(label, float(model_stats.total_cost))
                sessions_total.add_metric(label, model_stats.total_sessions)
                interactions_total.add_metric(label, model_stats.total_interactions)
                output_rate.add_metric(label, model_stats.p50_output_rate)

            yield tokens_input
            yield tokens_output
            yield tokens_cache_read
            yield tokens_cache_write
            yield cost
            yield sessions_total
            yield interactions_total
            yield output_rate

            # --- Session duration (no labels) ---
            duration = GaugeMetricFamily(
                "ocmonitor_session_duration_hours_total",
                "Total session duration in hours",
            )
            duration.add_metric([], total_duration_hours)
            yield duration

            # --- Per-project metrics ---
            sessions_by_project = GaugeMetricFamily(
                "ocmonitor_sessions_by_project",
                "Total sessions per project",
                labels=["project"],
            )
            for project_stats in project_report.project_stats:
                sessions_by_project.add_metric(
                    [project_stats.project_name], project_stats.total_sessions
                )
            yield sessions_by_project

        except Exception:
            logger.warning("Failed to collect metrics", exc_info=True)

            # Yield zero-valued metrics so Prometheus still gets valid responses
            model_labels = sorted(self._pricing_data.keys())
            for name, help_text in [
                ("ocmonitor_tokens_input_total", "Total input tokens"),
                ("ocmonitor_tokens_output_total", "Total output tokens"),
                ("ocmonitor_tokens_cache_read_total", "Total cache read tokens"),
                ("ocmonitor_tokens_cache_write_total", "Total cache write tokens"),
                ("ocmonitor_cost_dollars_total", "Total cost in USD"),
                ("ocmonitor_sessions_total", "Total number of sessions"),
                ("ocmonitor_interactions_total", "Total number of interactions"),
                ("ocmonitor_output_rate_tokens_per_second", "Median output tokens per second"),
            ]:
                g = GaugeMetricFamily(name, help_text, labels=["model"])
                for model_name in model_labels:
                    g.add_metric([model_name], 0)
                yield g

            duration = GaugeMetricFamily(
                "ocmonitor_session_duration_hours_total",
                "Total session duration in hours",
            )
            duration.add_metric([], 0)
            yield duration

            sessions_by_project = GaugeMetricFamily(
                "ocmonitor_sessions_by_project",
                "Total sessions per project",
                labels=["project"],
            )
            sessions_by_project.add_metric(["Unknown"], 0)
            yield sessions_by_project


class MetricsServer:
    """Lightweight HTTP server exposing Prometheus metrics."""

    def __init__(self, pricing_data: Dict[str, ModelPricing], host: str = "0.0.0.0", port: int = 9090):
        """Store server bind settings and pricing data for metric collection."""
        self.pricing_data = pricing_data
        self.host = host
        self.port = port

    def start(self):
        """Start the metrics HTTP server and block until interrupted."""
        registry = CollectorRegistry(auto_describe=False)
        collector = OCMonitorCollector(self.pricing_data)
        registry.register(collector)

        start_http_server(self.port, addr=self.host, registry=registry)

        # Block until KeyboardInterrupt
        threading.Event().wait()
