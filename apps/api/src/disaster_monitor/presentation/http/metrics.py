"""Low-cardinality Prometheus metrics for API and durable queue operations."""

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

from disaster_monitor.application.agent.diagnostics import AgentCapabilityDiagnostic
from disaster_monitor.domain.operations import IngestJobStatus


class OperationalMetrics:
    """Application-local registry so test/application factories remain isolated."""

    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        self.requests = Counter(
            "disastermonitor_http_requests_total",
            "Completed API requests.",
            ("method", "path", "status"),
            registry=self.registry,
        )
        self.request_duration = Histogram(
            "disastermonitor_http_request_duration_seconds",
            "API request duration.",
            ("method", "path"),
            registry=self.registry,
        )
        self.in_progress = Gauge(
            "disastermonitor_http_requests_in_progress",
            "API requests currently in progress.",
            registry=self.registry,
        )
        self.jobs = Gauge(
            "disastermonitor_ingest_jobs",
            "Durable ingestion jobs by queue state.",
            ("status",),
            registry=self.registry,
        )
        self.agent_capability_failures = Counter(
            "disastermonitor_agent_optional_capability_failures_total",
            "Optional agent capability failures by bounded capability and kind.",
            ("capability", "failure"),
            registry=self.registry,
        )

    def record(self, diagnostic: AgentCapabilityDiagnostic) -> None:
        self.agent_capability_failures.labels(
            capability=diagnostic.capability.value,
            failure=diagnostic.failure.value,
        ).inc()

    def update_jobs(self, counts: dict[IngestJobStatus, int]) -> None:
        for status in IngestJobStatus:
            self.jobs.labels(status=status.value).set(counts.get(status, 0))

    def render(self) -> tuple[bytes, str]:
        return generate_latest(self.registry), CONTENT_TYPE_LATEST
