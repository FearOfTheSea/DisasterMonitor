"""List inspection defers source interpretation without removing retained records."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from disaster_monitor.domain.disaster_types import Disaster
from disaster_monitor.domain.discovery import (
    AssessedReport,
    DiscoveryArticle,
    DiscoveryEvent,
    DiscoveryRun,
    ReportingInterval,
)
from disaster_monitor.domain.event_mentions import EventMention, MentionPlace
from disaster_monitor.domain.events import point_event_geometry
from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.domain.reported_impacts import extract_reported_impacts
from disaster_monitor.presentation.http import active_incident_serialization
from disaster_monitor.presentation.http.api import create_schema_app
from disaster_monitor.presentation.http.discovery_routes import scan_response

NOW = datetime(2026, 10, 17, 12, tzinfo=UTC)


def retained_run() -> DiscoveryRun:
    events = []
    reports = []
    for index, hazard in enumerate(Disaster):
        event_reports = []
        for scoped, count in ((False, 3), (True, 1)):
            title = f"Invented {hazard.value.replace('_', ' ')} report"
            line = f"The {hazard.value.replace('_', ' ')} killed {count} people."
            source = SourceReference(
                f"publisher-{index}-{scoped}",
                "Invented publisher",
                title,
                f"https://reports.example/{index}/{scoped}",
                NOW,
                None,
                NOW,
            )
            article = DiscoveryArticle(
                source, line, location="Invented district", bylines=("Example desk",)
            )
            mention = (
                EventMention(
                    f"mention-{index}",
                    source,
                    hazard,
                    line,
                    line,
                    place=MentionPlace("Invented district", "named_place"),
                    claims=extract_reported_impacts(line, source),
                )
                if scoped
                else None
            )
            report = AssessedReport(
                article, hazard, "eligible", (line,), mention=mention
            )
            event_reports.append(report)
            reports.append(report)
        events.append(
            DiscoveryEvent(
                f"event-{index}",
                hazard,
                "Invented district",
                None,
                point_event_geometry(10, 20, event_reports[0].article.source)
                if index % 2
                else None,
                tuple(event_reports),
                1,
            )
        )
    return DiscoveryRun(
        str(uuid4()),
        ReportingInterval.at_start(30, NOW),
        status="completed",
        finished_at=NOW,
        reports=tuple(reports),
        events=tuple(events),
    )


def test_summary_retains_all_search_map_source_and_identity_fields(monkeypatch):
    run = retained_run()
    full = scan_response(run).model_dump(mode="json")

    def forbidden(*args, **kwargs):
        raise AssertionError("Opening the list must not interpret article bodies.")

    monkeypatch.setattr(active_incident_serialization, "fatality_accounts", forbidden)
    monkeypatch.setattr(
        active_incident_serialization, "extract_reported_impacts", forbidden
    )
    summary = scan_response(run, reporting_detail="on_selection").model_dump(
        mode="json"
    )
    assert len(summary["snapshot"]["incidents"]) == len(Disaster)
    for complete, deferred in zip(
        full["snapshot"]["incidents"], summary["snapshot"]["incidents"], strict=True
    ):
        assert complete.pop("reporting_detail") == "full"
        assert deferred.pop("reporting_detail") == "on_selection"
        for original, preview in zip(
            complete["discovery_reports"], deferred["discovery_reports"], strict=True
        ):
            assert preview.pop("claims") == []
            assert preview.pop("fatality_evidence") == []
            original.pop("claims")
            original.pop("fatality_evidence")
    assert summary == full


@pytest.mark.parametrize("operation", ["read", "start", "continue", "reprocess"])
async def test_http_inspection_mode_is_explicit_and_full_remains_default(operation):
    run = retained_run()
    calls = []

    async def read(*args):
        calls.append(args)
        return run

    app = create_schema_app()
    app.state.dependencies = SimpleNamespace(
        discovery_scans=SimpleNamespace(
            get=read, start=read, continue_collection=read, reprocess=read
        )
    )
    path = "/api/v1/discovery-scans"
    if operation != "start":
        path += f"/{run.scan_id}"
    if operation in ("continue", "reprocess"):
        path += f"/{operation}"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        method = client.get if operation == "read" else client.post
        kwargs = {"json": {"reporting_days": 30}} if operation == "start" else {}
        full = await method(path, **kwargs)
        summary = await method(path + "?reporting_detail=on_selection", **kwargs)
        invalid = await method(path + "?reporting_detail=omit_records", **kwargs)
    assert full.is_success and summary.is_success
    assert invalid.status_code == 422 and len(calls) == 2
    assert summary.json()["scan_id"] == run.scan_id
    assert summary.json()["interval_start"] == full.json()["interval_start"]
    assert all(
        i["reporting_detail"] == "on_selection"
        for i in summary.json()["snapshot"]["incidents"]
    )
    assert all(
        i["reporting_detail"] == "full" for i in full.json()["snapshot"]["incidents"]
    )
    assert any(
        r["claims"]
        for i in full.json()["snapshot"]["incidents"]
        for r in i["discovery_reports"]
    )
