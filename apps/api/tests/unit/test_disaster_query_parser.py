from datetime import UTC, datetime

import pytest

from disaster_monitor.application.disaster import QueryParseStatus, RequestType
from disaster_monitor.application.services.disaster_query_parser import (
    DisasterQueryParser,
)
from disaster_monitor.domain.disaster import Hazard
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)

PARSER = DisasterQueryParser(StaticCountryCatalog())


@pytest.mark.parametrize(
    ("text", "hazard", "country_code"),
    [
        ("Latest earthquake in Japan", Hazard.EARTHQUAKE, "JPN"),
        ("Any news about earthquakes in Vietnam?", Hazard.EARTHQUAKE, "VNM"),
        ("Latest earthquakes in JP", Hazard.EARTHQUAKE, "JPN"),
        ("Current quake in JPN", Hazard.EARTHQUAKE, "JPN"),
        ("Current quakes in Nippon", Hazard.EARTHQUAKE, "JPN"),
        ("Latest flooding in Vietnam", Hazard.FLOOD, "VNM"),
        ("Latest wildfires in VNM", Hazard.WILDFIRE, "VNM"),
        ("Current forest fire in Viet Nam", Hazard.WILDFIRE, "VNM"),
        ("Latest tsunami in Venezuela", Hazard.TSUNAMI, "VEN"),
        ("Latest landslides in VE", Hazard.LANDSLIDE, "VEN"),
        ("Latest typhoon in Vietnam", Hazard.TROPICAL_CYCLONE, "VNM"),
        ("Latest hurricane in VEN", Hazard.TROPICAL_CYCLONE, "VEN"),
        ("Latest tropical cyclone in Vietnam", Hazard.TROPICAL_CYCLONE, "VNM"),
    ],
)
def test_parser_normalizes_hazard_and_country_aliases(
    text: str, hazard: Hazard, country_code: str
) -> None:
    result = PARSER.parse(text)

    assert result.status == QueryParseStatus.MATCHED
    assert result.query is not None
    assert result.query.hazard == hazard
    assert result.query.country.alpha3_code == country_code


def test_explicit_natural_date_uses_country_calendar_boundary() -> None:
    query = PARSER.parse("Latest earthquake in Japan on August 5, 2026").query

    assert query is not None
    assert query.date_from == datetime(2026, 8, 4, 15, 0, tzinfo=UTC)
    assert query.date_to == datetime(2026, 8, 5, 15, 0, tzinfo=UTC)
    assert query.time_intent == "specified"


@pytest.mark.parametrize(
    ("text", "status"),
    [
        ("Latest earthquake", QueryParseStatus.NO_COUNTRY),
        ("Latest update in Japan", QueryParseStatus.NO_HAZARD),
        (
            "Latest earthquake in Japan and Venezuela",
            QueryParseStatus.MULTIPLE_COUNTRIES,
        ),
        (
            "Latest earthquake and tsunami in Japan",
            QueryParseStatus.MULTIPLE_HAZARDS,
        ),
        ("Latest earthquake in Atlantis", QueryParseStatus.NO_COUNTRY),
        ("Latest earthquake in V", QueryParseStatus.NO_COUNTRY),
    ],
)
def test_parser_returns_explicit_limitations(
    text: str, status: QueryParseStatus
) -> None:
    assert PARSER.parse(text).status == status


def test_recognized_unsupported_hazard_is_still_current_disaster_intent() -> None:
    classification = PARSER.classify("Please give me the latest flood in Vietnam")

    assert classification.request_type == RequestType.CURRENT_DISASTER
    assert classification.query is not None
    assert classification.query.hazard == Hazard.FLOOD


def test_earthquake_news_is_current_disaster_intent() -> None:
    classification = PARSER.classify("Any news about earthquakes in Venezuela?")

    assert classification.request_type == RequestType.CURRENT_DISASTER
    assert classification.query is not None
    assert classification.query.country.alpha3_code == "VEN"
