from datetime import UTC, datetime

from disaster_monitor.application.disaster import SelectedEventSummary
from disaster_monitor.application.dto import ModelToolCall
from disaster_monitor.application.services.map_navigation import (
    FIT_COUNTRY_TOOL,
    MapNavigationService,
)
from disaster_monitor.domain.disaster import (
    Disaster,
    SourceReference,
    point_event_geometry,
)
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)


def test_country_tool_is_catalog_backed_and_executes_to_validated_bounds() -> None:
    service = MapNavigationService(StaticCountryCatalog())

    tool = service.model_tools()[0]
    action = service.execute_model_calls(
        (ModelToolCall(FIT_COUNTRY_TOOL, {"country_code": "JPN"}),),
        admitted_text="Zoom into Japan.",
    )

    assert tool.name == FIT_COUNTRY_TOOL
    assert tool.parameters["properties"] == {
        "country_code": {
            "type": "string",
            "enum": ["JPN", "VNM", "VEN"],
            "description": (
                "Supported country mappings: JPN = Japan; VNM = Vietnam; "
                "VEN = Venezuela."
            ),
        }
    }
    assert action is not None
    assert action.label == "Japan"
    assert action.bounds == (122.0, 20.0, 154.0, 46.0)


def test_country_tool_fails_closed_for_unallowlisted_or_ambiguous_calls() -> None:
    service = MapNavigationService(StaticCountryCatalog())

    assert (
        service.execute_model_calls(
            (ModelToolCall(FIT_COUNTRY_TOOL, {"country_code": "USA"}),),
            admitted_text="Zoom into Japan.",
        )
        is None
    )
    assert (
        service.execute_model_calls(
            (
                ModelToolCall(FIT_COUNTRY_TOOL, {"country_code": "JPN"}),
                ModelToolCall(FIT_COUNTRY_TOOL, {"country_code": "VNM"}),
            ),
            admitted_text="Show Japan and Vietnam.",
        )
        is None
    )
    assert (
        service.execute_model_calls(
            (
                ModelToolCall(
                    FIT_COUNTRY_TOOL,
                    {"country_code": "JPN", "zoom": 18},
                ),
            ),
            admitted_text="Zoom into Japan.",
        )
        is None
    )
    assert (
        service.execute_model_calls(
            (ModelToolCall(FIT_COUNTRY_TOOL, {"country_code": "VNM"}),),
            admitted_text="Zoom into Japan.",
        )
        is None
    )


def test_country_tool_does_not_navigate_for_a_disaster_question() -> None:
    service = MapNavigationService(StaticCountryCatalog())

    assert (
        service.execute_model_calls(
            (ModelToolCall(FIT_COUNTRY_TOOL, {"country_code": "JPN"}),),
            admitted_text="Latest news about cyclone in Japan.",
        )
        is None
    )


def test_investigation_case_fits_all_available_event_geometry_or_country_bounds() -> (
    None
):
    catalog = StaticCountryCatalog()
    service = MapNavigationService(catalog)
    country = catalog.get_by_alpha3("JPN")
    assert country is not None
    now = datetime(2026, 8, 5, 12, tzinfo=UTC)
    source = SourceReference(
        "fixture-source",
        "Fixture authority",
        "Fixture event",
        "https://example.test/event",
        now,
        now,
        now,
    )
    events = tuple(
        SelectedEventSummary(
            event_id=event_id,
            disaster=disaster,
            location="Fixture location",
            event_time=now,
            geometry=point_event_geometry(35, longitude, source),
            measurements=(),
            source=source,
            geography_status="in_country",
        )
        for event_id, disaster, longitude in (
            ("quake", Disaster.EARTHQUAKE, 179.0),
            ("slide", Disaster.LANDSLIDE, -179.0),
        )
    )

    action = service.for_investigation_case(
        selected_events=events,
        country=country,
    )
    fallback = service.for_investigation_case(selected_events=(), country=country)

    assert action is not None
    assert action.label == "Investigation case: Japan"
    assert action.bounds == (179.0, 35.0, 181.0, 35.0)
    assert fallback is not None and fallback.bounds == (122.0, 20.0, 154.0, 46.0)
