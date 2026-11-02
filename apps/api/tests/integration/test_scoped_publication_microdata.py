"""Only primary article microdata can supply a missing publication clock."""

from datetime import UTC, datetime

import pytest

from disaster_monitor.infrastructure.news.discovery_parser import (
    parse_discovery_article,
)

TITLE = "Remembering the Brookside earthquake"
STAMP = "2026-10-15T10:31:16+03:00"


def parse(body, preferred=""):
    return parse_discovery_article(
        f'<meta property="og:title" content="{TITLE}">{preferred}{body}',
        url="https://daily.example/report",
        title=TITLE,
        publisher="Daily",
        retrieved_at=datetime(2026, 11, 1, tzinfo=UTC),
        indexed_at=None,
    )


def article(metadata, *, headline=TITLE, kind="NewsArticle"):
    return (
        f'<article itemscope itemtype="https://schema.org/{kind}">'
        f"<h1>{headline}</h1><p>The earthquake killed hundreds in 2013.</p>"
        f"{metadata}</article>"
    )


@pytest.mark.parametrize("kind", ["NewsArticle", "Article", "ReportageNewsArticle"])
def test_owned_microdata_supplies_explicit_publication(kind):
    result = parse(
        article(f'<meta itemprop="datePublished" content="{STAMP}">', kind=kind)
    )
    assert result.source.published_at == datetime.fromisoformat(STAMP)
    assert result.source.publication_precision == "exact"
    assert result.source.updated_at is None
    assert result.source.retrieved_at == datetime(2026, 11, 1, tzinfo=UTC)


@pytest.mark.parametrize(
    "metadata",
    [
        f'<meta itemprop="dateModified" content="{STAMP}">',
        f'<meta itemprop="datePublished" content="{STAMP}" itemscope>',
        '<div itemscope itemtype="https://schema.org/Person">'
        f'<meta itemprop="datePublished" content="{STAMP}"></div>',
        f'<aside><meta itemprop="datePublished" content="{STAMP}"></aside>',
        '<meta itemprop="datePublished" content="2026-10-15T10:31:16">',
        '<meta itemprop="datePublished" content="invalid">',
        '<meta itemprop="headline" content="Other story">'
        f'<meta itemprop="datePublished" content="{STAMP}">',
        f'<meta itemprop="datePublished" content="{STAMP}">'
        '<meta itemprop="datePublished" content="2026-10-16">',
    ],
)
def test_unowned_conflicting_or_unusable_microdata_is_not_publication(metadata):
    assert parse(article(metadata)).source.published_at is None


def test_unscoped_date_and_other_article_headline_are_not_primary_metadata():
    marker = f'<meta itemprop="datePublished" content="{STAMP}">'
    assert parse(marker + article("", kind="WebPage")).source.published_at is None
    assert (
        parse(article(marker, headline="Other earthquake")).source.published_at is None
    )


def test_nested_related_article_does_not_supply_the_outer_article_clock():
    related = article(
        f'<meta itemprop="datePublished" content="{STAMP}">',
        headline="Other earthquake",
    )
    assert parse(article(related)).source.published_at is None


def test_nested_person_metadata_does_not_hide_later_owned_publication():
    metadata = (
        '<span itemscope itemtype="https://schema.org/Person">'
        '<meta itemprop="name" content="Reporter"></span>'
        f'<meta itemprop="datePublished" content="{STAMP}">'
        f'<meta itemprop="headline" content="{TITLE}">'
    )
    assert parse(article(metadata)).source.published_at == datetime.fromisoformat(STAMP)


def test_existing_explicit_publication_keeps_priority():
    result = parse(
        article(f'<meta itemprop="datePublished" content="{STAMP}">'),
        '<meta property="article:published_time" content="2026-10-14">',
    )
    assert result.source.published_at == datetime(2026, 10, 14, tzinfo=UTC)
    assert result.source.publication_precision == "day"


def test_conflicting_primary_microdata_blocks_remain_unresolved():
    body = article(f'<meta itemprop="datePublished" content="{STAMP}">')
    body += article('<meta itemprop="datePublished" content="2026-10-16">')
    assert parse(body).source.published_at is None


@pytest.mark.parametrize(
    "body",
    [
        '<a href="/other">'
        + article(f'<meta itemprop="datePublished" content="{STAMP}">')
        + "</a>",
        article(f'<h1>{TITLE}</h1><meta itemprop="datePublished" content="{STAMP}">'),
        "<div>" * 130 + article(f'<meta itemprop="datePublished" content="{STAMP}">'),
        "<div></div>" * 10_001
        + article(f'<meta itemprop="datePublished" content="{STAMP}">'),
    ],
)
def test_linked_duplicate_or_overbounded_headline_ownership_is_unresolved(body):
    assert parse(body).source.published_at is None


@pytest.mark.parametrize(
    "marker, expected, precision",
    [
        (
            f'<time itemprop="datePublished" datetime="{STAMP}">15 October</time>',
            datetime.fromisoformat(STAMP),
            "exact",
        ),
        (
            '<meta itemprop="datePublished" content="2026-10-15">',
            datetime(2026, 10, 15, tzinfo=UTC),
            "day",
        ),
    ],
)
def test_owned_explicit_clock_preserves_its_precision(marker, expected, precision):
    result = parse(article(marker))
    assert result.source.published_at == expected
    assert result.source.publication_precision == precision
