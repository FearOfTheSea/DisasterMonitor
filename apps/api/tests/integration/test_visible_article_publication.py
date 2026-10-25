"""Only primary article publication markers can supply a visible source date."""

from datetime import UTC, datetime

import pytest

from disaster_monitor.infrastructure.news.discovery_parser import (
    parse_discovery_article,
)

NOW = datetime(2026, 10, 24, tzinfo=UTC)


def parse(markup):
    return parse_discovery_article(
        markup,
        url="https://daily.example/report",
        title="Local report",
        publisher="Daily",
        retrieved_at=NOW,
        indexed_at=NOW,
    )


@pytest.mark.parametrize(
    "clock",
    [
        '<time class="entry-date published updated">Publicado el 14-10-2026</time>',
        '<time itemprop="datePublished" datetime="2026-10-14">14 October 2026</time>',
        '<header><time class="published">Published: October 14, 2026</time></header>',
    ],
)
def test_primary_semantic_article_owns_its_publication_day(clock):
    article = parse(
        f"<article><h1>Local report</h1>{clock}<p>A flood killed two.</p></article>"
    )
    assert article.source.published_at == datetime(2026, 10, 14, tzinfo=UTC)
    assert article.source.publication_precision == "day"
    assert article.event_time is None


def test_published_datetime_keeps_an_explicit_offset():
    article = parse("""<article><h1>Local report</h1>
      <time class="published" datetime="2026-10-14T09:41:00-05:00">Published</time>
      <p>A flood killed two.</p></article>""")
    assert article.source.published_at == datetime.fromisoformat(
        "2026-10-14T09:41:00-05:00"
    )
    assert article.source.publication_precision == "exact"


def test_headline_owned_posted_block_does_not_guess_a_timezone_from_an_abbreviation():
    article = parse("""<div class="content-header"><h1>Local report</h1>
      <div class="content-date-posted">
      <span>Posted:</span> Oct 19, 2026 9:41 PM CDT</div>
      </div>
      <div class="content-body">
      <p>A flood killed two.</p>
      <p>A retained second paragraph.</p>
      </div>
      <h1>Weather forecast</h1>
      <time class="published">Published: October 24, 2026</time>""")
    assert article.source.published_at == datetime(2026, 10, 19, tzinfo=UTC)
    assert article.source.publication_precision == "day"
    assert "retained second paragraph" in article.text
    assert "Weather forecast" not in article.text


@pytest.mark.parametrize(
    "markup",
    [
        (
            '<time class="published">Publicado el 14-10-2026</time><article>'
            "<h1>Local report</h1><p>Flood report.</p></article>"
        ),
        (
            "<article><h1>Other report</h1>"
            '<time class="published">Publicado el 14-10-2026</time></article>'
        ),
        (
            '<article><h1><a href="/other">Local report</a></h1>'
            '<time class="published">Publicado el 14-10-2026</time></article>'
        ),
        (
            "<article><h1>Local report</h1>"
            '<time class="updated">Publicado el 14-10-2026</time></article>'
        ),
        "<article><h1>Local report</h1><time>October 14, 2026</time></article>",
        (
            "<article><h1>Local report</h1>"
            "<p>The flood struck on October 14, 2026.</p></article>"
        ),
        (
            "<div><h1>Local report</h1>"
            '<div class="content-date-posted">Posted: October 14, 2026</div>'
            "</div>"
        ),
        (
            '<div class="content-header"><h1>Other report</h1>'
            '<div class="content-date-posted">Posted: October 14, 2026</div>'
            "</div>"
        ),
        (
            '<article><h1>Local report</h1><div class="related">'
            '<time class="published">Published: October 14, 2026</time></div>'
            "</article>"
        ),
        (
            "<article><h1>Local report</h1><aside>"
            '<time class="published">Published: October 14, 2026</time>'
            "</aside></article>"
        ),
        (
            "<article><h1>Local report</h1>"
            '<time class="published" hidden>Published: October 14, 2026</time>'
            "</article>"
        ),
        (
            "<article><h1>Local report</h1>"
            '<time class="published">Publicado el 31-02-2026</time></article>'
        ),
        (
            "<article><h1>Local report</h1>"
            '<time class="published">Updated: October 14, 2026</time>'
            "</article>"
        ),
        (
            "<article><h1>Local report</h1>"
            '<time class="published">The flood struck on October 14, 2026</time>'
            "</article>"
        ),
    ],
)
def test_unowned_updated_hidden_and_occurrence_dates_are_not_publication(markup):
    article = parse(markup)
    assert article.source.published_at is None
    assert article.source.publication_precision == "unknown"
    assert article.source.retrieved_at == NOW
    assert article.indexed_at == NOW


def test_primary_headline_does_not_borrow_a_nested_articles_date():
    article = parse("""<article><h1>Local report</h1><p>A flood killed two.</p>
      <article>
      <h1>Other report</h1>
      <time class="published">Published: October 14, 2026</time>
      </article>
      </article>""")
    assert article.source.published_at is None


def test_conflicting_primary_publication_markers_remain_unknown():
    article = parse("""<article><h1>Local report</h1>
      <time class="published">Published: October 14, 2026</time>
      <time class="published">Published: October 15, 2026</time></article>""")
    assert article.source.published_at is None


def test_explicit_metadata_remains_the_primary_publication_source():
    article = parse("""
      <meta property="article:published_time" content="2026-10-13T20:00:00Z">
      <article>
      <h1>Local report</h1>
      <time class="published">Published: October 14, 2026</time>
      </article>""")
    assert article.source.published_at == datetime(2026, 10, 13, 20, tzinfo=UTC)
    assert article.source.publication_precision == "exact"


@pytest.mark.parametrize("brand", ["Daily", "Dáily"])
def test_a_site_brand_suffix_does_not_hide_the_primary_headlines_clock(brand):
    article = parse_discovery_article(
        '<article><h1>Local report</h1><time class="published">'
        "Publicado el 14-10-2026</time></article>",
        url="https://daily.example/report",
        title=f"Local report » {brand}",
        publisher="daily.example",
        retrieved_at=NOW,
        indexed_at=None,
    )
    assert article.source.published_at == datetime(2026, 10, 14, tzinfo=UTC)


@pytest.mark.parametrize(
    "title",
    ["Local report » Other", "Local report extra", "Local report » Daily weather"],
)
def test_a_shared_prefix_without_the_site_brand_does_not_establish_headline_ownership(
    title,
):
    article = parse_discovery_article(
        '<article><h1>Local report</h1><time class="published">'
        "Publicado el 14-10-2026</time></article>",
        url="https://daily.example/report",
        title=title,
        publisher="daily.example",
        retrieved_at=NOW,
        indexed_at=None,
    )
    assert article.source.published_at is None
