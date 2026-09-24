"""Regression coverage for place uncertainty and bounded discovery metadata."""

from datetime import UTC, datetime

from disaster_monitor.application.agent.models import (
    AgentExecutionState,
    InvestigationPlan,
    TaskKind,
    ValidatedDisasterTask,
)
from disaster_monitor.application.agent.tools.coordination_tools import compose_report
from disaster_monitor.application.disaster import (
    DisasterQuery,
    ProviderBatch,
    ProviderIssue,
)
from disaster_monitor.application.investigation.disaster_report_renderer import (
    DisasterReportRenderer,
)
from disaster_monitor.application.investigation.run_disaster_agent import _summary
from disaster_monitor.domain.disaster import (
    Country,
    Disaster,
    DisasterEvent,
    GeographicArea,
    SourceReference,
)

NOW = datetime(2026, 8, 5, 12, tzinfo=UTC)


def test_unverified_named_place_reports_country_candidate_without_attribution() -> None:
    country = Country("TST", "Testland", (), GeographicArea(0, 10, 0, 10), "UTC")
    source = SourceReference(
        "testland-floods",
        "Test authority",
        "Flood event",
        "https://example.test/flood",
        NOW,
        NOW,
        NOW,
    )
    event = DisasterEvent(
        "test:flood-1", Disaster.FLOOD, "Testland", country, NOW, source
    )
    query = DisasterQuery(
        Disaster.FLOOD, country, "recent", ("latest",), location_hint="North Province"
    )
    task = ValidatedDisasterTask(
        "Was North Province flooded?",
        TaskKind.INVESTIGATION,
        True,
        Disaster.FLOOD,
        country,
        query=query,
    )
    state = AgentExecutionState(task, InvestigationPlan("p", "test", ()))
    state.workspace.place_candidates = (event,)

    report = compose_report(state, DisasterReportRenderer(), NOW)

    assert report.response_type == "current_disaster_place_unverified"
    assert report.selected_event is None
    assert report.sources == (source,)
    assert "North Province" in report.message
    assert "Testland" in report.message
    assert "https://example.test/flood" in report.message
    assert "confirmed in North Province" not in report.message


def test_investigation_summary_exposes_bounded_event_discovery_diagnostics() -> None:
    country = Country("TST", "Testland", (), GeographicArea(0, 10, 0, 10), "UTC")
    task = ValidatedDisasterTask(
        "Flood in Testland",
        TaskKind.INVESTIGATION,
        True,
        Disaster.FLOOD,
        country,
    )
    state = AgentExecutionState(task, InvestigationPlan("p", "test", ()))
    state.workspace.event_batch = ProviderBatch(
        issues=(
            ProviderIssue(
                "test", "Limit reached", reason_code="acquisition_limit_reached"
            ),
        ),
        scan_complete=False,
        records_seen=50,
    )

    summary = _summary(state)

    assert summary.event_records_seen == 50
    assert summary.event_scan_complete is False
    assert summary.event_issue_codes == ("acquisition_limit_reached",)
    assert summary.physical_event_count == 0
    assert summary.place_candidate_count == 0
