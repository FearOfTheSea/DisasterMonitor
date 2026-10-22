"""Duplicate templates must not erase one unambiguous publisher publication."""

import json
from datetime import UTC, datetime

import pytest

from disaster_monitor.infrastructure.news.discovery_parser import (
    parse_discovery_article,
)

URL = "https://publisher.example/report"
RICH = {
    "@type": "NewsArticle",
    "mainEntityOfPage": {"@type": "WebPage", "@id": URL},
    "headline": "Flood in Lakeview",
    "datePublished": "2026-10-22T07:45:43+02:00",
    "articleBody": "Flooding killed two people in Lakeview. Ten homes were damaged.",
}


def parse(objects):
    return parse_discovery_article(
        '<script type="application/ld+json">' + json.dumps(objects) + "</script>",
        url=URL,
        title="Index hint",
        publisher="Daily",
        retrieved_at=datetime(2026, 10, 22, 8, tzinfo=UTC),
        indexed_at=None,
    )


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("stub_date", [None, ""])
def test_dated_primary_article_wins_over_its_undated_same_identity_template(
    reverse, stub_date
):
    stub = dict(RICH, datePublished=stub_date, articleBody="Flood damage was reported.")
    article = parse([stub, RICH] if reverse else [RICH, stub])
    assert article.source.published_at == datetime(2026, 10, 22, 5, 45, 43, tzinfo=UTC)
    assert article.text == RICH["articleBody"]
    assert article.source.title == "Flood in Lakeview"


def test_identical_primary_schema_duplicates_do_not_create_publication_ambiguity():
    article = parse([RICH, dict(RICH)])
    assert article.source.published_at is not None
    assert article.text == RICH["articleBody"]


@pytest.mark.parametrize(
    "conflict",
    [
        {"datePublished": "2026-10-20T07:45:43+02:00"},
        {"datePublished": "", "headline": "Wildfire in Highforest"},
    ],
)
def test_conflicting_identified_article_dates_or_headlines_remain_unresolved(conflict):
    article = parse([RICH, dict(RICH, **conflict)])
    assert article.source.published_at is None


def test_dated_other_article_never_supplies_the_matching_undated_articles_clock():
    article = parse(
        [
            dict(RICH, mainEntityOfPage={"@id": "https://publisher.example/other"}),
            dict(RICH, datePublished=""),
        ]
    )
    assert article.source.published_at is None
