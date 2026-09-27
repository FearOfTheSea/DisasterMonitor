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
    point_event_geometry,
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
    assert "GDACS alert level Green (source: GDACS" in details
    assert usgs.canonical_url in details
    assert gdacs.canonical_url in details


def test_summary_flags_materially_different_source_depths() -> None:
    now = datetime(2026, 9, 27, tzinfo=UTC)
    country = Country("PNG", "Papua New Guinea", (), GeographicArea(-12, 0, 140, 156))
    usgs = SourceReference(
        "usgs-earthquakes",
        "United States Geological Survey",
        "M 5.6 near Kokopo",
        "https://earthquake.usgs.gov/earthquakes/eventpage/us6000txtc",
        now,
        now,
        now,
    )
    emsc = SourceReference(
        "emsc-earthquakes",
        "Euro-Mediterranean Seismological Centre",
        "New Britain region",
        "https://www.seismicportal.eu/eventdetails.html?unid=20260926_0000148",
        now,
        now,
        now,
    )
    event = DisasterEvent(
        "usgs:us6000txtc",
        Disaster.EARTHQUAKE,
        "74 km ESE of Kokopo, Papua New Guinea",
        country,
        datetime(2026, 9, 26, 14, 8, tzinfo=UTC),
        usgs,
        measurements=(
            EventMeasurement(MeasurementKind.DEPTH, 57.78, "km", source=usgs),
            EventMeasurement(MeasurementKind.DEPTH, 10, "km", source=emsc),
        ),
    )
    packet = EvidencePacket(
        DisasterQuery(Disaster.EARTHQUAKE, country, "dated", ()),
        event,
        (),
        (),
        (usgs, emsc),
        (),
        (),
        now,
        False,
    )

    _, sections = DisasterReportRenderer().render(packet)
    summary = next(
        item.content for item in sections if item.title == "Situation summary"
    )

    assert "depths differ across sources" in summary
    assert "10 km" in summary
    assert "57.78 km" in summary


def test_gdacs_burned_area_is_labelled_as_a_source_estimate() -> None:
    now = datetime(2026, 9, 26, 20, tzinfo=UTC)
    country = Country("AGO", "Angola", (), GeographicArea(-19, -4, 11, 24))
    source = SourceReference(
        "gdacs-wildfires",
        "GDACS; source: GWIS",
        "Forest fires in Angola",
        "https://www.gdacs.org/report.aspx?eventtype=WF&eventid=1032415",
        now,
        now,
        now,
    )
    event = DisasterEvent(
        "gdacs:wf:1032415",
        Disaster.WILDFIRE,
        "Angola",
        country,
        datetime(2026, 9, 24, tzinfo=UTC),
        source,
        measurements=(
            EventMeasurement(MeasurementKind.BURNED_AREA, 7065, "ha", source=source),
        ),
    )
    packet = EvidencePacket(
        DisasterQuery(Disaster.WILDFIRE, country, "specified", ()),
        event,
        (),
        (),
        (source,),
        (),
        (),
        now,
        False,
    )

    _, sections = DisasterReportRenderer().render(packet)

    assert "GDACS/GWIS burned-area estimate 7065 ha" in sections[0].content
    assert "GDACS/GWIS burned-area estimate 7065 ha" in sections[1].content


def test_gdacs_flood_report_explains_event_window_and_centroid() -> None:
    now = datetime(2026, 9, 27, 1, tzinfo=UTC)
    country = Country("VNM", "Vietnam", (), GeographicArea(8, 24, 102, 110))
    source = SourceReference(
        "gdacs-floods",
        "GDACS; source: GLOFAS",
        "Flood in Vietnam",
        "https://www.gdacs.org/report.aspx?eventtype=FL&eventid=1104141",
        now,
        now,
        now,
    )
    event = DisasterEvent(
        "gdacs:fl:1104141",
        Disaster.FLOOD,
        "Vietnam",
        country,
        datetime(2026, 9, 3, 1, tzinfo=UTC),
        source,
        event_time_end=datetime(2026, 9, 27, 0, 50, tzinfo=UTC),
        geometry=point_event_geometry(10.78, 106.66, source),
    )
    packet = EvidencePacket(
        DisasterQuery(Disaster.FLOOD, country, "dated", ()),
        event,
        (),
        (),
        (source,),
        (),
        (),
        now,
        False,
    )

    _, sections = DisasterReportRenderer().render(packet)
    summary = next(
        item.content for item in sections if item.title == "Situation summary"
    )
    details = next(item.content for item in sections if item.title == "Event details")

    assert "through 2026-09-27T00:50:00Z" in summary
    assert (
        "event-list point is a locator, not a satellite-observed flood extent"
        in details
    )


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
        "gdacs-floods",
        "GDACS",
        "Flood in Vietnam",
        "https://www.gdacs.org/Floods/report.aspx?eventid=1104141",
        now,
        now,
        now,
    )
    event = DisasterEvent(
        "gdacs:fl:1104141",
        Disaster.FLOOD,
        "Nghe An Province, Vietnam",
        country,
        now,
        source,
    )
    facts = tuple(
        ReportedFact(
            "buildings_damaged",
            f"Reported houses damaged — {region}",
            "749",
            FactStatus.PRELIMINARY,
            source,
            reported_location=region,
        )
        for region in ("Ngh? An Province", "Phu Tho Province", "Vietnam")
    )
    packet = EvidencePacket(
        DisasterQuery(
            Disaster.FLOOD,
            country,
            "recent",
            (),
            location_hint="Nghệ An Province, Vietnam",
        ),
        event,
        facts,
        (),
        (source,),
        (),
        (),
        now,
        False,
    )

    _, sections = DisasterReportRenderer().render(packet)
    damage = next(
        section.content
        for section in sections
        if section.title == "Physical and infrastructure damage"
    )

    assert "Ngh? An Province" in damage
    assert "Phu Tho" not in damage
    assert "— Vietnam" not in damage
    assert "2 other-area or country-wide" in damage


def test_report_leads_with_event_and_bounded_impact_answer() -> None:
    now = datetime(2026, 9, 25, 20, tzinfo=UTC)
    country = Country(
        "MEX", "Mexico", (), GeographicArea(14, 33, -119, -86), "UTC-06:00"
    )
    source = SourceReference(
        "gdacs-tropical-cyclones",
        "GDACS",
        "Tropical Cyclone POLO-26",
        "https://www.gdacs.org/report.aspx?eventtype=TC&eventid=1001325",
        now,
        now,
        now,
    )
    event = DisasterEvent(
        "gdacs:tc:1001325",
        Disaster.TROPICAL_CYCLONE,
        "Mexico",
        country,
        datetime(2026, 9, 21, 3, tzinfo=UTC),
        source,
        measurements=(
            EventMeasurement(MeasurementKind.SEVERITY, "Orange", source=source),
            EventMeasurement(
                MeasurementKind.MAXIMUM_WIND_SPEED, 287, "km/h", source=source
            ),
        ),
    )
    packet = EvidencePacket(
        DisasterQuery(Disaster.TROPICAL_CYCLONE, country, "recent", ()),
        event,
        (),
        (),
        (source,),
        (),
        (),
        now,
        False,
    )

    _, sections = DisasterReportRenderer().render(packet)
    summary = sections[0].content
    details = sections[1].content

    assert "Tropical Cyclone POLO-26" in summary
    assert "Mexico" in summary
    assert "21 Sep 2026" in summary
    assert "GDACS alert level Orange" in summary
    assert "GDACS maximum wind-speed estimate 287 km/h" in summary
    assert "no event-specific human-impact or damage figures" in summary.lower()
    assert "gdacs:tc:1001325" not in summary
    assert "https://" not in summary
    assert "tropical_cyclone" not in summary
    assert "GDACS alert level Orange" in details


def test_report_does_not_repeat_eruption_name_or_provider_whitespace() -> None:
    now = datetime(2026, 9, 25, 20, tzinfo=UTC)
    country = Country(
        "RUS", "Russian Federation", (), GeographicArea(41, 82, -180, 180)
    )
    source = SourceReference(
        "gdacs-volcanic-eruptions",
        "GDACS",
        "Eruption Chikurachki",
        "https://www.gdacs.org/report.aspx?eventtype=VO&eventid=1000149",
        now,
        now,
        now,
    )
    event = DisasterEvent(
        "gdacs:vo:1000149",
        Disaster.VOLCANIC_ERUPTION,
        "Eruption  Chikurachki",
        country,
        now,
        source,
    )
    packet = EvidencePacket(
        DisasterQuery(Disaster.VOLCANIC_ERUPTION, country, "recent", ()),
        event,
        (),
        (),
        (source,),
        (),
        (),
        now,
        False,
    )

    _, sections = DisasterReportRenderer().render(packet)

    assert "Eruption Chikurachki — Eruption Chikurachki" not in sections[0].content
    assert "Eruption  Chikurachki" not in sections[1].content


def test_report_summary_labels_preliminary_impact_without_erasing_source_detail() -> (
    None
):
    now = datetime(2026, 9, 25, 20, tzinfo=UTC)
    country = Country("VNM", "Vietnam", (), GeographicArea(8, 24, 102, 110))
    source = SourceReference(
        "gdacs-floods",
        "GDACS",
        "Flood in Vietnam",
        "https://www.gdacs.org/report.aspx?eventtype=FL&eventid=10",
        now,
        now,
        now,
    )
    event = DisasterEvent(
        "gdacs:fl:10", Disaster.FLOOD, "Vietnam", country, now, source
    )
    fact = ReportedFact(
        "fatalities", "People reported dead", "2", FactStatus.PRELIMINARY, source
    )
    packet = EvidencePacket(
        DisasterQuery(Disaster.FLOOD, country, "recent", ()),
        event,
        (fact,),
        (),
        (source,),
        (),
        (),
        now,
        False,
    )

    _, sections = DisasterReportRenderer().render(packet)

    assert "People reported dead: 2 (preliminary)" in sections[0].content
    assert source.canonical_url in sections[2].content
