from datetime import UTC, datetime, timedelta

from disaster_monitor.application.disaster import DisasterQuery, EvidencePacket
from disaster_monitor.application.services.disaster_report_renderer import (
    DisasterReportRenderer,
)
from disaster_monitor.application.services.evidence_reconciliation import (
    build_evidence_packet,
    correlate_situation_report,
)
from disaster_monitor.domain.disaster import (
    CorrelationStatus,
    DisasterEvent,
    FactStatus,
    Hazard,
    ReportedFact,
    SituationReport,
    SourceAuthority,
    SourceReference,
)
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)

NOW = datetime(2026, 8, 6, 3, 0, tzinfo=UTC)
CATALOG = StaticCountryCatalog()
JAPAN = CATALOG.get_by_alpha3("JPN")
VENEZUELA = CATALOG.get_by_alpha3("VEN")
assert JAPAN is not None and VENEZUELA is not None


def _source(
    publisher: str,
    authority: SourceAuthority = SourceAuthority.SECONDARY,
    *,
    age: timedelta = timedelta(),
) -> SourceReference:
    timestamp = NOW - age
    return SourceReference(
        publisher,
        f"{publisher} update",
        f"https://example.test/{publisher.lower()}",
        timestamp,
        timestamp,
        NOW,
        authority,
    )


def _event(hazard: Hazard = Hazard.EARTHQUAKE) -> DisasterEvent:
    return DisasterEvent(
        "usgs:target",
        hazard,
        "Sucre, Venezuela",
        VENEZUELA,
        NOW - timedelta(hours=2),
        _source("USGS", SourceAuthority.SCIENTIFIC_AUTHORITY),
        latitude=10.4,
        longitude=-63.5,
        magnitude=6.2 if hazard == Hazard.EARTHQUAKE else None,
    )


def test_country_neutral_correlation_uses_hazard_and_country_code() -> None:
    event = _event()
    report = SituationReport(
        _source("Authority", SourceAuthority.NATIONAL_AUTHORITY),
        "Impacts were reported in Sucre.",
        reported_event_time=event.event_time,
        locations=("Sucre",),
        countries=("Venezuela",),
        country_codes=("VEN",),
        hazard=Hazard.EARTHQUAKE,
    )

    assert correlate_situation_report(report, event) == CorrelationStatus.MATCHED
    assert (
        correlate_situation_report(
            SituationReport(
                report.source,
                report.narrative,
                reported_event_time=event.event_time,
                locations=("Sucre",),
                country_codes=("JPN",),
                hazard=Hazard.EARTHQUAKE,
            ),
            event,
        )
        == CorrelationStatus.UNMATCHED
    )
    assert (
        correlate_situation_report(
            SituationReport(
                report.source,
                report.narrative,
                reported_event_time=event.event_time,
                locations=("Sucre",),
                country_codes=("VEN",),
                hazard=Hazard.FLOOD,
            ),
            event,
        )
        == CorrelationStatus.UNMATCHED
    )


def test_typed_authority_outranks_newer_secondary_fact() -> None:
    event = _event()
    query = DisasterQuery(Hazard.EARTHQUAKE, VENEZUELA, "recent", ("damage",))
    official = _source(
        "National authority", SourceAuthority.NATIONAL_AUTHORITY, age=timedelta(hours=2)
    )
    secondary = _source("Secondary bulletin", age=timedelta(minutes=5))

    def report(source: SourceReference, value: str) -> SituationReport:
        return SituationReport(
            source,
            f"Buildings damaged: {value}",
            facts=(
                ReportedFact(
                    "buildings",
                    "Buildings damaged",
                    value,
                    FactStatus.CONFIRMED,
                    source,
                    event.event_id,
                    claim_id="buildings",
                ),
            ),
            event_id=event.event_id,
            country_codes=("VEN",),
            hazard=Hazard.EARTHQUAKE,
        )

    packet = build_evidence_packet(
        query,
        event,
        (report(secondary, "9"), report(official, "4")),
        warnings=(),
        retrieved_at=NOW,
    )

    assert packet.facts[0].value == "4"
    assert packet.facts[0].source.authority == SourceAuthority.NATIONAL_AUTHORITY


def test_generic_renderer_uses_selected_hazard_and_country_without_japan_prose() -> (
    None
):
    event = _event(Hazard.FLOOD)
    query = DisasterQuery(Hazard.FLOOD, VENEZUELA, "recent", ("latest",))
    packet = EvidencePacket(
        query,
        event,
        (),
        (),
        (event.source,),
        (),
        (),
        NOW,
        False,
    )

    message, sections = DisasterReportRenderer().render(packet)

    assert "flood" in message
    assert "Venezuela" in message
    assert "Japan" not in message
    assert "earthquake" not in message
    assert all(section.title != "Tsunami and secondary hazards" for section in sections)
