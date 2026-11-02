"""An unusable publication field must not mask another explicit publisher clock."""

from datetime import UTC, datetime

import pytest

from disaster_monitor.infrastructure.news.discovery_parser import (
    parse_discovery_article,
)

NOW = datetime(2026, 11, 1, tzinfo=UTC)


def parse(metadata):
    return parse_discovery_article(
        '<meta property="og:type" content="article">'
        '<meta property="og:title" content="Flood in Brookside">'
        + metadata
        + "<article><h1>Flood in Brookside</h1>"
        "<p>One person died in the flood.</p></article>",
        url="https://daily.example/report",
        title="Flood in Brookside",
        publisher="Daily",
        retrieved_at=NOW,
        indexed_at=NOW,
    )


@pytest.mark.parametrize("unusable", ["2026-10-30 09:39:27", "not a timestamp", ""])
def test_explicit_named_publication_with_offset_survives_unusable_preferred_field(
    unusable,
):
    article = parse(
        f'<meta property="article:published_time" content="{unusable}">'
        '<meta name="datePublished" content="2026-10-30T09:39:27+08:00">'
    )
    assert article.source.published_at == datetime.fromisoformat(
        "2026-10-30T09:39:27+08:00"
    )
    assert article.source.publication_precision == "exact"
    assert article.indexed_at == NOW and article.source.retrieved_at == NOW


def test_valid_primary_structured_publication_is_not_masked_by_naive_meta_clock():
    article = parse(
        '<meta property="article:published_time" content="2026-10-30 09:39:27">'
        '<script type="application/ld+json">{"@type":"NewsArticle",'
        '"url":"https://daily.example/report","headline":"Flood in Brookside",'
        '"datePublished":"2026-10-30T09:39:27+08:00"}</script>'
    )
    assert article.source.published_at == datetime.fromisoformat(
        "2026-10-30T09:39:27+08:00"
    )


@pytest.mark.parametrize(
    "other",
    [
        '<meta name="dateModified" content="2026-10-30T09:39:27+08:00">',
        '<meta property="article:modified_time" content="2026-10-30T09:39:27+08:00">',
        '<meta name="date" content="2026-10-30T09:39:27+08:00">',
    ],
)
def test_update_generic_date_and_index_clocks_do_not_repair_unknown_publication(other):
    article = parse(
        '<meta property="article:published_time" content="2026-10-30 09:39:27">' + other
    )
    assert article.source.published_at is None
    assert article.source.publication_precision == "unknown"


def test_a_valid_preferred_publication_keeps_its_existing_priority_and_precision():
    article = parse(
        '<meta property="article:published_time" content="2026-10-29">'
        '<meta name="datePublished" content="2026-10-30T09:39:27+08:00">'
    )
    assert article.source.published_at == datetime(2026, 10, 29, tzinfo=UTC)
    assert article.source.publication_precision == "day"
