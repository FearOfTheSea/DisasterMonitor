"""Merged event measurements retain their own source attribution."""

from dataclasses import replace
from datetime import UTC, datetime

from disaster_monitor.application.disaster import DisasterQuery, EvidencePacket
from disaster_monitor.application.investigation.disaster_report_renderer import (
    DisasterReportRenderer,
)
from disaster_monitor.domain.disaster import (
    Country,
    Disaster,
    DisasterEvent,
    EventMeasurement,
    FactStatus,
    GeographicArea,
    MeasurementKind,
    ReportedFact,
    SourceReference,
)


def test_merged_measurements_cite_their_own_sources() -> None:
    now = datetime(2026, 9, 22, 12, tzinfo=UTC)
    country = Country("JPN", "Japan", (), GeographicArea(20, 46, 122, 154), "UTC+09:00")
    usgs = SourceReference(
        "usgs-earthquakes",
        "USGS",
        "M 5.1 near Uken",
        "https://earthquake.usgs.gov/earthquakes/eventpage/us7000tj4y",
        now,
        now,
        now,
    )
    gdacs = SourceReference(
        "gdacs-earthquakes",
        "GDACS",
        "Earthquake in Japan",
        "https://www.gdacs.org/report.aspx?eventid=1567485&eventtype=EQ",
        now,
        now,
        now,
    )
    event = DisasterEvent(
        "usgs:us7000tj4y",
        Disaster.EARTHQUAKE,
        "88 km NNW of Uken, Japan",
        country,
        now,
        usgs,
        measurements=(
            EventMeasurement(MeasurementKind.MAGNITUDE, 5.1, source=usgs),
            EventMeasurement(MeasurementKind.SEVERITY, "Green", source=gdacs),
        ),
    )
    packet = EvidencePacket(
        DisasterQuery(Disaster.EARTHQUAKE, country, "recent", ()),
        event,
        (),
        (),
        (usgs, gdacs),
        (),
        (),
        now,
        False,
    )

    _, sections = DisasterReportRenderer().render(packet)
    details = next(
        section.content for section in sections if section.title == "Event details"
    )

    assert "magnitude 5.1 (source: USGS" in details
    assert "severity Green (source: GDACS" in details
    assert usgs.canonical_url in details
    assert gdacs.canonical_url in details


def test_named_place_cites_its_report_separately_from_event_feed() -> None:
    now = datetime(2026, 9, 24, tzinfo=UTC)
    country = Country(
        "VNM", "Vietnam", (), GeographicArea(8, 24, 102, 110), "UTC+07:00"
    )
    feed = SourceReference(
        "gdacs-floods",
        "GDACS",
        "Flood in Vietnam",
        "https://www.gdacs.org/gdacsapi/api/events/geteventdata?eventid=1104141",
        now,
        now,
        now,
    )
    report_source = replace(
        feed,
        title="Nghe An Province, Vietnam, Mid September 2026",
        canonical_url="https://www.gdacs.org/report.aspx?episodeid=6&eventid=1104141",
    )
    event = DisasterEvent(
        "gdacs:fl:1104141",
        Disaster.FLOOD,
        "Nghe An Province, Vietnam",
        country,
        now,
        feed,
        location_source=report_source,
    )
    packet = EvidencePacket(
        DisasterQuery(Disaster.FLOOD, country, "recent", ()),
        event,
        (),
        (),
        (feed, report_source),
        (),
        (),
        now,
        False,
    )

    _, sections = DisasterReportRenderer().render(packet)
    details = next(
        section.content for section in sections if section.title == "Event details"
    )

    assert "Location source: GDACS" in details
    assert report_source.canonical_url in details
    assert "Event source: GDACS" in details
    assert feed.canonical_url in details


def test_named_place_report_omits_facts_from_other_regions() -> None:
    now = datetime(2026, 9, 24, tzinfo=UTC)
    country = Country(
        "VNM", "Vietnam", (), GeographicArea(8, 24, 102, 110), "UTC+07:00"
    )
    source = SourceReference(
        "gdacs-floods", "GDACS", "Flood in Vietnam",
        "https://www.gdacs.org/Floods/report.aspx?eventid=1104141",
        now, now, now,
    )
    event = DisasterEvent(
        "gdacs:fl:1104141", Disaster.FLOOD, "Nghe An Province, Vietnam",
        country, now, source,
    )
    facts = tuple(
        ReportedFact(
            "buildings_damaged", f"Reported houses damaged — {region}", "749",
            FactStatus.PRELIMINARY, source, reported_location=region,
        )
        for region in ("Ngh? An Province", "Phu Tho Province", "Vietnam")
    )
    packet = EvidencePacket(
        DisasterQuery(
            Disaster.FLOOD, country, "recent", (),
            location_hint="Nghệ An Province, Vietnam",
        ),
        event, facts, (), (source,), (), (), now, False,
    )

    _, sections = DisasterReportRenderer().render(packet)
    damage = next(
        section.content for section in sections
        if section.title == "Physical and infrastructure damage"
    )

    assert "Ngh? An Province" in damage
    assert "Phu Tho" not in damage
    assert "— Vietnam" not in damage
    assert "2 other-area or country-wide" in damage
