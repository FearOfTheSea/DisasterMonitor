"""An explicit hazard clock survives separate response language in its sentence."""

from datetime import UTC, datetime

import pytest

from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.domain.mention_extraction import extract_mentions

SOURCE = SourceReference(
    "news",
    "Daily",
    "Regional flood update",
    "https://news.example/story",
    datetime(2026, 10, 23, tzinfo=UTC),
    None,
    datetime(2026, 10, 23, tzinfo=UTC),
)


@pytest.mark.parametrize(
    ("text", "start", "end", "precision"),
    [
        (
            "The disaster revived memories of the September 2022 floods, which "
            "killed twelve people in Riverton and prompted criticism "
            "of the emergency response.",
            datetime(2022, 9, 1, tzinfo=UTC),
            datetime(2022, 10, 1, tzinfo=UTC),
            "range",
        ),
        (
            "The investigation focuses on the response to the flood on August 4, 2023, "
            "that killed three campers.",
            datetime(2023, 8, 4, tzinfo=UTC),
            datetime(2023, 8, 5, tzinfo=UTC),
            "day",
        ),
        (
            "Emergency teams arrived after the flood struck Riverton on 4 August 2023 "
            "and killed three people.",
            datetime(2023, 8, 4, tzinfo=UTC),
            datetime(2023, 8, 5, tzinfo=UTC),
            "day",
        ),
        (
            "On 4 August 2023, floods struck Riverton and killed three people before "
            "medical teams arrived.",
            datetime(2023, 8, 4, tzinfo=UTC),
            datetime(2023, 8, 5, tzinfo=UTC),
            "day",
        ),
    ],
)
def test_a_date_owned_by_the_hazard_is_not_lost_to_other_activity(
    text, start, end, precision
):
    mentions = extract_mentions(text, SOURCE)
    dated = [m for m in mentions if m.time and m.time.start]
    assert len(dated) == 1
    assert dated[0].time.start == start
    assert dated[0].time.end == end
    assert dated[0].time.precision == precision
    assert dated[0].role == "historical"
    deaths = [c for c in dated[0].claims if c.fact.category == "fatalities"]
    assert deaths
    assert all("historical" in c.qualifiers for c in deaths)


@pytest.mark.parametrize(
    "text",
    [
        "The flood struck Riverton and rescuers arrived on 4 August 2023.",
        "The response to the flood was announced on 4 August 2023 "
        "after three people died.",
        "On 4 August 2023 flood response teams arrived "
        "after the flood killed three people.",
        "On 4 August 2023 flood victims were treated after three people died.",
        "On 4 August 2023 flood warnings were published "
        "after the flood killed three people.",
        "A photograph on 4 August 2023 shows the flood that killed three people.",
        "On 4 August 2023 officials said floods had killed three people in Riverton.",
        "The flood report was published on 4 August 2023 after three people died.",
    ],
)
def test_response_care_statement_and_media_dates_stay_separate_from_the_hazard(text):
    mentions = extract_mentions(text, SOURCE)
    assert mentions
    assert all(m.time is None or m.time.start is None for m in mentions)


def test_two_occurrence_periods_cannot_inherit_the_preceding_current_flood_clock():
    mentions = extract_mentions(
        "Flooding in Riverton in July 2026 damaged homes. Residents were rebuilding "
        "from devastating flooding in July 2025, which killed more than 100 people, "
        "when storms struck again in July 2026 and caused further damage.",
        SOURCE,
    )
    fatal = [
        m for m in mentions if any(c.fact.category == "fatalities" for c in m.claims)
    ]
    assert fatal
    assert all(m.time is not None and m.time.start is None for m in fatal)
    assert all(
        "July 2025" in m.time.wording and "July 2026" in m.time.wording for m in fatal
    )
    assert all(m.time.wording in m.text for m in fatal)
    assert all(any("unresolved" in n for n in m.notices) for m in fatal)


def test_an_activity_period_does_not_make_an_explicit_hazard_period_ambiguous():
    (mention,) = extract_mentions(
        "The September 2022 floods killed three people and response teams arrived "
        "in October 2022.",
        SOURCE,
    )
    assert mention.time.start == datetime(2022, 9, 1, tzinfo=UTC)
    assert mention.time.end == datetime(2022, 10, 1, tzinfo=UTC)
