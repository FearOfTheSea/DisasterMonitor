"""A reported calendar period is bounded uncertainty, not an exact onset."""

from datetime import UTC, datetime, timedelta

import pytest

from disaster_monitor.domain.disaster_types import (
    EventTimePrecision,
    ObservationKind,
    event_temporality_overlaps,
    validate_event_temporality,
)

START = datetime(2021, 12, 1, tzinfo=UTC)
END = datetime(2022, 1, 1, tzinfo=UTC)


def test_calendar_period_overlaps_its_last_date_but_not_its_exclusive_end():
    validate_event_temporality(
        START, END, EventTimePrecision.RANGE, ObservationKind.PHYSICAL_EVENT
    )
    assert event_temporality_overlaps(
        START, END, EventTimePrecision.RANGE, END - timedelta(days=1), END
    )
    assert not event_temporality_overlaps(
        START, END, EventTimePrecision.RANGE, END, END + timedelta(days=1)
    )


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (START, None),
        (START, START),
        (START, START - timedelta(days=1)),
        (START.replace(tzinfo=None), END),
        (START, END.replace(tzinfo=None)),
        (START + timedelta(hours=1), END),
    ],
)
def test_invalid_calendar_bounds_are_rejected_explicitly(start, end):
    with pytest.raises(ValueError):
        validate_event_temporality(
            start, end, EventTimePrecision.RANGE, ObservationKind.PHYSICAL_EVENT
        )
