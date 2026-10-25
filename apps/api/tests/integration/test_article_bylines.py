"""Publisher-declared bylines are attribution, not original-report identities."""

import json
from datetime import UTC, datetime

import pytest

from disaster_monitor.infrastructure.news.discovery_parser import (
    parse_discovery_article,
)

NOW = datetime(2026, 10, 25, tzinfo=UTC)
URL = "https://publisher.example/report"


def parse(markup):
    return parse_discovery_article(
        markup,
        url=URL,
        title="Flood report",
        publisher="Daily",
        retrieved_at=NOW,
        indexed_at=None,
    )


@pytest.mark.parametrize("key", ["articleAuthor", "author"])
def test_page_byline_keeps_the_publishing_outlet_and_unknown_report_origin(key):
    article = parse(
        f'<meta name="{key}" content="  News   Agency  ">'
        '<meta property="og:site_name" content="Local Daily">'
        "<article><p>Floodwaters killed two people.</p></article>"
    )
    assert article.bylines == ("News Agency",)
    assert article.source.publisher == "Local Daily"
    assert article.source.canonical_url == URL
    assert article.origin is None
    assert article.text == "Floodwaters killed two people."


@pytest.mark.parametrize(
    "authors,expected",
    [
        ("Jane Reporter", ("Jane Reporter",)),
        ({"@type": "Person", "name": "Jane Reporter"}, ("Jane Reporter",)),
        (
            {
                "@type": "Organization",
                "name": "News Agency",
                "url": "https://agency.example/",
            },
            ("News Agency",),
        ),
        (
            [{"name": "Jane Reporter"}, {"name": "News Agency"}],
            ("Jane Reporter", "News Agency"),
        ),
    ],
)
def test_only_the_owned_primary_article_supplies_jsonld_bylines(authors, expected):
    objects = [
        {
            "@type": "NewsArticle",
            "url": "https://publisher.example/other",
            "author": {"name": "Unrelated Author"},
        },
        {"@type": "NewsArticle", "url": URL, "author": authors},
        {"@type": "Person", "name": "Site Owner"},
    ]
    article = parse(
        '<script type="application/ld+json">' + json.dumps(objects) + "</script>"
    )
    assert article.bylines == expected
    assert article.origin is None


def test_duplicate_and_distinct_attribution_spelling_is_preserved_without_guessing():
    article = parse(
        '<meta name="author" content="News Agency">'
        '<script type="application/ld+json">'
        + json.dumps(
            {
                "@type": "NewsArticle",
                "url": URL,
                "author": [{"name": "News Agency"}, {"name": "Jane Reporter"}],
            }
        )
        + "</script>"
    )
    assert article.bylines == ("News Agency", "Jane Reporter")


@pytest.mark.parametrize(
    "author", [None, {}, {"url": "https://agency.example/"}, {"name": " "}, 4]
)
def test_missing_names_are_not_invented_from_homepages_or_publisher_names(author):
    article = parse(
        '<script type="application/ld+json">'
        + json.dumps(
            {
                "@type": "NewsArticle",
                "url": URL,
                "author": author,
                "publisher": {"name": "Daily"},
            }
        )
        + "</script>"
    )
    assert article.bylines == ()
    assert article.source.publisher == "Daily"


def test_an_explicit_report_origin_stays_separate_from_its_author_credit():
    article = parse(
        '<script type="application/ld+json">'
        + json.dumps(
            {
                "@type": "NewsArticle",
                "url": URL,
                "author": {"name": "News Agency"},
                "isBasedOn": "https://agency.example/original-story",
            }
        )
        + "</script>"
    )
    assert article.bylines == ("News Agency",)
    assert article.origin == "https://agency.example/original-story"


def test_ambiguous_article_objects_do_not_borrow_a_byline():
    article = parse(
        '<script type="application/ld+json">'
        + json.dumps(
            [
                {"@type": "NewsArticle", "author": {"name": "One"}},
                {"@type": "NewsArticle", "author": {"name": "Two"}},
            ]
        )
        + "</script>"
    )
    assert article.bylines == ()


def test_related_article_body_metadata_does_not_supply_the_page_byline():
    article = parse(
        "<main><article><p>Floodwaters killed two people.</p></article>"
        '<article><meta name="author" content="Other Author">'
        "<p>Another story.</p></article></main>"
    )
    assert article.bylines == ()


def test_repeated_page_author_names_are_preserved_without_duplicate_credit():
    article = parse(
        '<meta name="author" content="Jane Reporter">'
        '<meta name="author" content="News Agency">'
        '<meta name="articleAuthor" content="NEWS AGENCY">'
    )
    assert article.bylines == ("Jane Reporter", "News Agency")


@pytest.mark.parametrize("byline", ["https://agency.example/", "A" * 257])
def test_missing_name_or_oversized_credit_is_not_replaced_by_an_invented_name(byline):
    article = parse(f'<meta name="author" content="{byline}">')
    assert article.bylines == ()
