"""Physical release wording owns its date; publication-year guesses stay bounded."""

from datetime import UTC, datetime

import pytest

from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.domain.mention_extraction import extract_mentions

NOW = datetime(2026, 10, 24, tzinfo=UTC)
SOURCE = SourceReference(
    "news", "Daily", "Regional account", "https://daily.example/story", NOW, None, NOW
)


@pytest.mark.parametrize(
    "location", ["", " in Riverton", " in Riverton, North Province,"]
)
def test_a_physical_hazard_unleashing_chaos_owns_its_explicit_day(location):
    text = (
        "It was around 3:30 p.m. on August 4, 2023, "
        f"and a flood{location} had unleashed chaos near Bridge Road."
    )
    (mention,) = extract_mentions(text, SOURCE)
    assert mention.role == "historical"
    assert mention.time.wording == "August 4, 2023"
    assert mention.time.start == datetime(2023, 8, 4, tzinfo=UTC)
    assert mention.time.end == datetime(2023, 8, 5, tzinfo=UTC)
    assert mention.time.precision == "day"
    assert not mention.time.year_inferred


@pytest.mark.parametrize(
    "text",
    [
        "On August 4, 2023 officials said a flood had unleashed chaos in Riverton.",
        "The flood report on August 4, 2023 unleashed criticism in Riverton.",
        "Flood response teams unleashed a publicity campaign on August 4, 2023.",
        "A flood could have unleashed chaos on August 4, 2023.",
        "A photograph on August 4, 2023 shows a flood that unleashed chaos.",
    ],
)
def test_statements_response_forecasts_and_photos_do_not_supply_onset(text):
    mentions = extract_mentions(text, SOURCE)
    assert mentions
    assert all(m.time is None or m.time.start is None for m in mentions)


def test_a_repeated_day_cannot_guess_a_new_year_against_an_explicit_hazard_day():
    mentions = extract_mentions(
        "A flood struck Riverton on August 4, 2023. "
        "Records show firefighters fielded calls on August 4 once flooding started "
        "in Lakeview. Despite the deaths, rescuers continued working.",
        SOURCE,
    )
    repeated = [m for m in mentions if "Records show" in m.text]
    assert repeated
    assert all(m.time and m.time.wording == "August 4" for m in repeated)
    assert all(m.time.start is None and m.time.precision == "unknown" for m in repeated)
    assert any("year" in n and "unresolved" in n for m in repeated for n in m.notices)
    assert any(c.fact.category == "fatalities" for m in repeated for c in m.claims)
    assert any(
        m.time and m.time.start == datetime(2023, 8, 4, tzinfo=UTC) for m in mentions
    )


@pytest.mark.parametrize("explicit_year", [2023, 2026])
def test_explicit_years_never_get_replaced_by_a_different_articles_date(explicit_year):
    mentions = extract_mentions(
        "A flood struck Riverton on August 4, 2023. "
        f"A separate flood hit Lakeview on August 4, {explicit_year} "
        "and killed two people.",
        SOURCE,
    )
    assert any(
        m.time
        and m.time.start == datetime(explicit_year, 8, 4, tzinfo=UTC)
        and not m.time.year_inferred
        and "Lakeview" in m.text
        for m in mentions
    )


def test_another_day_does_not_cancel_a_normal_publication_year_inference():
    mentions = extract_mentions(
        "A flood struck Riverton on August 4, 2023. "
        "A separate flood hit Lakeview on August 5 and killed two people.",
        SOURCE,
    )
    assert any(
        m.time and m.time.start == datetime(2026, 8, 5, tzinfo=UTC) for m in mentions
    )


def test_a_matching_calendar_day_for_another_hazard_does_not_override_the_year():
    mentions = extract_mentions(
        "An earthquake struck Riverton on August 4, 2023. "
        "A flood hit Lakeview on August 4 and killed two people.",
        SOURCE,
    )
    assert any(
        m.time and m.time.start == datetime(2026, 8, 4, tzinfo=UTC) for m in mentions
    )


def test_an_independent_publisher_section_does_not_override_the_year():
    mentions = extract_mentions(
        "A flood struck Riverton on August 4, 2023.\n##\n"
        "A flood hit Lakeview on August 4 and killed two people.",
        SOURCE,
    )
    assert any(
        m.time and m.time.start == datetime(2026, 8, 4, tzinfo=UTC) for m in mentions
    )
