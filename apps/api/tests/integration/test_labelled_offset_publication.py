"""An explicit offset remains authoritative in a labelled publisher clock."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from disaster_monitor.infrastructure.news.discovery_parser import (
    parse_discovery_article,
)

NOW = datetime(2026, 11, 5, tzinfo=UTC)


def article(clock, *, updated="2026-11-04T12:00:00Z"):
    return parse_discovery_article(
        '<meta property="og:title" content="River flooding report">'
        f'<meta property="article:published_time" content="{clock}">'
        f'<meta property="article:modified_time" content="{updated}">'
        "<article><h1>River flooding report</h1>"
        "<p>Flooding affected the town.</p></article>",
        url="https://daily.example/report",
        title="River flooding report",
        publisher="Daily",
        retrieved_at=NOW,
        indexed_at=NOW,
    )


@pytest.mark.parametrize(
    ("clock", "offset"),
    [
        ("2026-10-12CEST08:18:39+02:00", 2),
        ("2026-10-12CEST08:18:39+0200", 2),
        ("2026-10-12CET08:18:39+01:00", 1),
        ("2026-10-12CET08:18:39+0100", 1),
    ],
)
def test_known_label_and_consistent_explicit_offset_keep_the_original_clock(
    clock, offset
):
    result = article(clock)
    assert result.source.published_at == datetime(
        2026, 10, 12, 8, 18, 39, tzinfo=timezone(timedelta(hours=offset))
    )
    assert result.source.publication_precision == "exact"
    assert result.source.updated_at == datetime(2026, 11, 4, 12, tzinfo=UTC)
    assert result.indexed_at == NOW


@pytest.mark.parametrize(
    "clock",
    [
        "2026-10-12CEST08:18:39+01:00",
        "2026-10-12CET08:18:39+02:00",
        "2026-10-12CEST08:18:39",
        "2026-10-12CET08:18:39",
        "2026-10-12XYZ08:18:39+02:00",
        "2026-10-12CEST28:18:39+02:00",
    ],
)
def test_unknown_contradictory_or_missing_offset_does_not_invent_original_publication(
    clock,
):
    result = article(clock)
    assert result.source.published_at is None
    assert result.source.publication_precision == "unknown"
    assert result.source.updated_at is not None
