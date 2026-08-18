from datetime import UTC, datetime, timedelta

import pytest

from disaster_monitor.application.disaster import (
    DisasterQuery,
    EventDiscriminator,
)
from disaster_monitor.application.services.current_disaster_report import (
    CurrentDisasterReportService,
)
from disaster_monitor.application.services.disaster_query_parser import (
    DisasterQueryParser,
)
from disaster_monitor.application.services.disaster_report_renderer import (
    render_source_backed_report,
)
from disaster_monitor.application.services.event_resolution import (
    cluster_physical_events,
    resolve_recent_event,
)
from disaster_monitor.application.services.evidence_correlation import (
    EarthquakeEvidenceCorrelationPolicy,
)
from disaster_monitor.application.services.evidence_reconciliation import (
    EvidenceReconciler,
    build_evidence_packet,
    correlate_situation_report,
)
from disaster_monitor.application.services.provider_registry import (
    ProviderCapabilities,
    ProviderRole,
)
from disaster_monitor.domain.disaster import (
    CorrelationStatus,
    EarthquakeEvent,
    EventMeasurement,
    FactStatus,
    Hazard,
    MeasurementKind,
    ReportedFact,
    SituationReport,
    SourceReference,
    point_event_geometry,
)
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)

NOW = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
CATALOG = StaticCountryCatalog()
PARSER = DisasterQueryParser(CATALOG)
JAPAN = CATALOG.get_by_alpha3("JPN")
assert JAPAN is not None


def _source(publisher: str, title: str) -> SourceReference:
    return SourceReference(
        source_id=f"test-{publisher.lower().replace(' ', '-')}",
        publisher=publisher,
        title=title,
        canonical_url=f"https://example.test/{title.replace(' ', '-')}",
        published_at=NOW,
        updated_at=NOW,
        retrieved_at=NOW,
    )


def _event(
    event_id: str,
    *,
    hours_old: int = 2,
    location: str = "Ishikawa, Japan",
    latitude: float = 37.0,
    longitude: float = 137.0,
    magnitude: float = 6.0,
    aftershock: bool = False,
    parent_event_id: str | None = None,
) -> EarthquakeEvent:
    source = _source("USGS", event_id)
    return EarthquakeEvent(
        event_id=event_id,
        hazard=Hazard.EARTHQUAKE,
        location=location,
        country=JAPAN,
        event_time=NOW - timedelta(hours=hours_old),
        source=source,
        geometry=point_event_geometry(latitude, longitude, source),
        measurements=(
            EventMeasurement(MeasurementKind.MAGNITUDE, magnitude, source=source),
            EventMeasurement(
                MeasurementKind.PROVIDER_SIGNIFICANCE,
                magnitude * 100,
                source=source,
            ),
        ),
        is_aftershock=aftershock,
        parent_event_id=parent_event_id,
        provider_ids=(event_id,),
    )


def _query(**kwargs: object) -> DisasterQuery:
    magnitude = kwargs.pop("magnitude", None)
    event_identifier = kwargs.pop("event_identifier", None)
    values: dict[str, object] = {
        "hazard": Hazard.EARTHQUAKE,
        "country": JAPAN,
        "time_intent": "recent",
        "focus": ("damage",),
    }
    values.update(kwargs)
    discriminators = []
    if magnitude is not None:
        discriminators.append(EventDiscriminator("magnitude", str(magnitude)))
    if event_identifier is not None:
        discriminators.append(EventDiscriminator("event_id", str(event_identifier)))
    values["event_discriminators"] = tuple(discriminators)
    return DisasterQuery(**values)  # type: ignore[arg-type]


def test_date_and_each_event_discriminator_narrows_resolution() -> None:
    query = PARSER.parse(
        "Latest earthquake in Japan on 2026-08-05 in Ishikawa Prefecture "
        "near Kanazawa City at 37.0, 137.0, magnitude 6.0."
    ).query
    assert query is not None
    assert query.date_from is not None and query.date_to is not None
    assert query.date_to > query.date_from
    assert query.prefecture == "Ishikawa"
    assert query.city == "Kanazawa"
    assert query.latitude == 37.0
    assert query.longitude == 137.0
    assert query.discriminator("magnitude") == "6.0"

    candidates = (
        _event("target", location="Ishikawa, Japan"),
        _event(
            "other",
            hours_old=30,
            location="Tokyo, Japan",
            latitude=35.7,
            longitude=139.7,
            magnitude=5.0,
        ),
    )
    selected = resolve_recent_event(
        candidates,
        _query(date_from=query.date_from, date_to=query.date_to),
        now=NOW,
    )
    assert selected.selected == candidates[0]

    assert (
        resolve_recent_event(
            candidates,
            _query(prefecture="Ishikawa"),
            now=NOW,
        ).selected
        == candidates[0]
    )
    assert (
        resolve_recent_event(
            candidates,
            _query(city="Tokyo"),
            now=NOW,
        ).selected
        == candidates[1]
    )
    assert (
        resolve_recent_event(
            candidates,
            _query(latitude=35.7, longitude=139.7),
            now=NOW,
        ).selected
        == candidates[1]
    )
    assert (
        resolve_recent_event(
            candidates,
            _query(magnitude=5.0),
            now=NOW,
        ).selected
        == candidates[1]
    )
    assert (
        resolve_recent_event(
            candidates,
            _query(event_identifier="other"),
            now=NOW,
        ).selected
        == candidates[1]
    )


def test_event_sequence_requires_more_than_an_aftershock_label() -> None:
    mainshock = _event("mainshock", hours_old=8, magnitude=6.8)
    nearby_aftershock = _event(
        "aftershock", hours_old=1, magnitude=4.2, latitude=37.1, aftershock=True
    )
    distant_aftershock = _event(
        "distant-aftershock",
        hours_old=1,
        magnitude=4.2,
        latitude=43.0,
        longitude=145.0,
        aftershock=True,
    )
    old_aftershock = _event(
        "old-aftershock",
        hours_old=100,
        magnitude=4.2,
        aftershock=True,
        parent_event_id="mainshock",
    )
    assert (
        resolve_recent_event(
            (mainshock, nearby_aftershock), _query(), now=NOW
        ).ambiguous
        is False
    )
    assert resolve_recent_event(
        (mainshock, distant_aftershock), _query(), now=NOW
    ).ambiguous
    assert (
        resolve_recent_event((mainshock, old_aftershock), _query(), now=NOW).selected
        == mainshock
    )


def test_jma_and_usgs_observations_are_one_event_with_both_ids() -> None:
    jma = _event("jma:20260805100000", magnitude=5.9)
    usgs = _event("usgs:us7000fixture", magnitude=6.0)
    normalized = cluster_physical_events((jma, usgs))
    assert len(normalized) == 1
    assert set(normalized[0].provider_ids) == {
        "jma:20260805100000",
        "usgs:us7000fixture",
    }
    assert "jma:20260805100000" in normalized[0].provider_ids


def test_qualified_provider_ids_do_not_collide_across_namespaces() -> None:
    selected = _event("jma:shared")

    assert selected.has_provider_id("jma:shared")
    assert selected.has_provider_id("shared")
    assert not selected.has_provider_id("usgs:shared")


def test_rejected_report_cannot_contribute_facts_and_narrative_is_preserved() -> None:
    event = _event("usgs:target")
    good_source = _source("ReliefWeb", "Ishikawa update")
    bad_source = _source("ReliefWeb", "Tokyo update")
    good = SituationReport(
        source=good_source,
        narrative="A named airport closed and shelters opened in Ishikawa.",
        facts=(
            ReportedFact(
                category="airports",
                label="Airport closure",
                value="closed",
                status=FactStatus.PRELIMINARY,
                source=good_source,
            ),
        ),
        correlation=CorrelationStatus.MATCHED,
        event_id=event.event_id,
    )
    bad = SituationReport(
        source=bad_source,
        narrative="Tokyo airport closed after another Japan earthquake.",
        facts=(
            ReportedFact(
                category="airports",
                label="Airport closure",
                value="Tokyo airport closed",
                status=FactStatus.CONFIRMED,
                source=bad_source,
            ),
        ),
        correlation=CorrelationStatus.UNMATCHED,
    )
    assert correlate_situation_report(bad, event) == CorrelationStatus.UNMATCHED
    packet = build_evidence_packet(
        _query(), event, (good, bad), warnings=(), retrieved_at=NOW
    )
    message, _ = render_source_backed_report(packet)
    assert "Tokyo airport" not in message
    assert "airport closed" in message
    assert good_source.canonical_url in message


def test_generic_correlation_does_not_match_equal_magnitude_without_neutral_clues() -> (
    None
):
    event = _event("usgs:target", magnitude=6.0)
    source = _source("ReliefWeb", "unrelated report")
    report = SituationReport(
        source=source,
        narrative="A report with magnitude 6.0 but no matching location or date.",
        countries=(JAPAN.canonical_name,),
        measurements=(EventMeasurement(MeasurementKind.MAGNITUDE, 6.0, source=source),),
    )

    assert correlate_situation_report(report, event) == CorrelationStatus.UNMATCHED


def test_earthquake_magnitude_correlation_is_owned_by_its_policy() -> None:
    event = _event("usgs:target", magnitude=6.0)
    source = _source("ReliefWeb", "Ishikawa report")
    report = SituationReport(
        source=source,
        narrative="Ishikawa earthquake report with magnitude 6.0.",
        locations=("Ishikawa",),
        measurements=(EventMeasurement(MeasurementKind.MAGNITUDE, 6.0, source=source),),
    )

    assert (
        EarthquakeEvidenceCorrelationPolicy().correlate(report, event)
        == CorrelationStatus.MATCHED
    )


def test_hazard_parser_does_not_apply_earthquake_discriminators_to_other_hazards() -> (
    None
):
    result = PARSER.parse(
        "Latest flood in Japan, magnitude 6.0, provider event us7000fixture."
    )

    assert result.query is not None
    assert result.query.event_discriminators == ()


def test_injected_correlation_policy_is_applied_once_by_reconciler() -> None:
    event = _event("usgs:target")
    source = _source("ReliefWeb", "Ishikawa update")
    report = SituationReport(
        source=source,
        narrative="Ishikawa earthquake update.",
        locations=("Ishikawa",),
        correlation=CorrelationStatus.UNMATCHED,
    )
    calls = 0

    class CountingPolicy:
        def correlate(self, _report, _event):
            nonlocal calls
            calls += 1
            return CorrelationStatus.MATCHED

    class CountingPolicies:
        def for_hazard(self, _hazard):
            return CountingPolicy()

    packet = EvidenceReconciler(CountingPolicies()).build(
        _query(),
        event,
        (report,),
        warnings=(),
        retrieved_at=NOW,
    )

    assert calls == 1
    assert packet.narratives and report.narrative in packet.narratives[0]


@pytest.mark.asyncio
async def test_event_without_situation_records_is_explicitly_partial() -> None:
    class Events:
        async def find_recent_events(self, _query, *, now):
            return (_event("usgs:verified"),)

    class NoSituation:
        async def get_situation_reports(self, _event, _query, *, now):
            return ()

    result = await CurrentDisasterReportService(
        Events(),
        NoSituation(),
        provider_capabilities=(
            ProviderCapabilities(
                frozenset({ProviderRole.EVENT_DISCOVERY}),
                frozenset({Hazard.EARTHQUAKE}),
                None,
            ),
            ProviderCapabilities(
                frozenset({ProviderRole.SITUATION_EVIDENCE}),
                frozenset({Hazard.EARTHQUAKE}),
                None,
            ),
        ),
        clock=lambda: NOW,
    ).execute(_query())
    assert result.selected_event is not None
    assert result.partial is True
    assert any("does not mean" in warning for warning in result.warnings)
