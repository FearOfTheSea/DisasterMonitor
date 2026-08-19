from datetime import UTC, datetime

import pytest

from disaster_monitor.application.disaster import QueryParseStatus, RequestType
from disaster_monitor.application.services.disaster_query_parser import (
    DisasterQueryParser,
)
from disaster_monitor.domain.disaster import Disaster
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)

PARSER = DisasterQueryParser(StaticCountryCatalog())


@pytest.mark.parametrize(
    ("text", "disaster", "country_code"),
    [
        ("Latest earthquake in Japan", Disaster.EARTHQUAKE, "JPN"),
        ("Any news about earthquakes in Vietnam?", Disaster.EARTHQUAKE, "VNM"),
        ("Latest earthquakes in JP", Disaster.EARTHQUAKE, "JPN"),
        ("Current quake in JPN", Disaster.EARTHQUAKE, "JPN"),
        ("Current quakes in Nippon", Disaster.EARTHQUAKE, "JPN"),
        ("Latest flooding in Vietnam", Disaster.FLOOD, "VNM"),
        ("Latest wildfires in VNM", Disaster.WILDFIRE, "VNM"),
        ("Current forest fire in Viet Nam", Disaster.WILDFIRE, "VNM"),
        ("Latest landslides in VE", Disaster.LANDSLIDE, "VEN"),
        ("Latest typhoon in Vietnam", Disaster.TROPICAL_CYCLONE, "VNM"),
        ("Latest typhoons in Vietnam", Disaster.TROPICAL_CYCLONE, "VNM"),
        ("Latest hurricane in VEN", Disaster.TROPICAL_CYCLONE, "VEN"),
        ("Latest hurricanes in VEN", Disaster.TROPICAL_CYCLONE, "VEN"),
        ("Latest cyclone in Japan", Disaster.TROPICAL_CYCLONE, "JPN"),
        ("Latest cyclones in Japan", Disaster.TROPICAL_CYCLONE, "JPN"),
        ("Latest tropical cyclone in Vietnam", Disaster.TROPICAL_CYCLONE, "VNM"),
        ("Latest tropical cyclones in Vietnam", Disaster.TROPICAL_CYCLONE, "VNM"),
        ("Latest volcanic eruption in Japan", Disaster.VOLCANIC_ERUPTION, "JPN"),
        ("Latest volcanic eruptions in Vietnam", Disaster.VOLCANIC_ERUPTION, "VNM"),
        ("Latest volcano eruption in Japan", Disaster.VOLCANIC_ERUPTION, "JPN"),
        ("Latest volcano eruptions in Japan", Disaster.VOLCANIC_ERUPTION, "JPN"),
        ("Latest erupting volcano in Japan", Disaster.VOLCANIC_ERUPTION, "JPN"),
        ("Latest erupting volcanoes in Japan", Disaster.VOLCANIC_ERUPTION, "JPN"),
        ("Última erupción volcánica en Japón", Disaster.VOLCANIC_ERUPTION, "JPN"),
        ("Últimas erupciones volcánicas en Japón", Disaster.VOLCANIC_ERUPTION, "JPN"),
        ("Phun trào núi lửa gần đây ở Việt Nam", Disaster.VOLCANIC_ERUPTION, "VNM"),
        ("最近の火山噴火 in 日本", Disaster.VOLCANIC_ERUPTION, "JPN"),
    ],
)
def test_parser_normalizes_disaster_and_country_aliases(
    text: str, disaster: Disaster, country_code: str
) -> None:
    result = PARSER.parse(text)

    assert result.status == QueryParseStatus.MATCHED
    assert result.query is not None
    assert result.query.disaster == disaster
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
        ("Latest update in Japan", QueryParseStatus.NO_DISASTER),
        (
            "Latest earthquake in Japan and Venezuela",
            QueryParseStatus.MULTIPLE_COUNTRIES,
        ),
        (
            "Latest earthquake and flood in Japan",
            QueryParseStatus.MULTIPLE_DISASTERS,
        ),
        ("Latest earthquake in Atlantis", QueryParseStatus.NO_COUNTRY),
        ("Latest earthquake in V", QueryParseStatus.NO_COUNTRY),
    ],
)
def test_parser_returns_explicit_limitations(
    text: str, status: QueryParseStatus
) -> None:
    assert PARSER.parse(text).status == status


def test_recognized_unsupported_disaster_is_still_current_disaster_intent() -> None:
    classification = PARSER.classify("Please give me the latest flood in Vietnam")

    assert classification.request_type == RequestType.CURRENT_DISASTER
    assert classification.query is not None
    assert classification.query.disaster == Disaster.FLOOD


def test_earthquake_news_is_current_disaster_intent() -> None:
    classification = PARSER.classify("Any news about earthquakes in Venezuela?")

    assert classification.request_type == RequestType.CURRENT_DISASTER
    assert classification.query is not None
    assert classification.query.country.alpha3_code == "VEN"


@pytest.mark.parametrize("text", ("Latest volcano in Japan", "Any volcanoes in Japan?"))
def test_bare_volcano_terms_are_not_current_eruption_aliases(text: str) -> None:
    assert PARSER.parse(text).status == QueryParseStatus.NO_DISASTER


def test_bare_eruption_is_not_a_disaster_alias() -> None:
    assert (
        PARSER.parse("Latest eruption in Japan").status == QueryParseStatus.NO_DISASTER
    )
