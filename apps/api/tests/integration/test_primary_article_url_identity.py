"""HTTPS default-port spelling must not hide an owned article's publication."""

import json
from datetime import UTC, datetime

import pytest

from disaster_monitor.infrastructure.news.discovery_parser import (
    parse_discovery_article,
)

URL = "https://publisher.example/news/report?edition=one"


def parse(requested, declared, kind):
    news = {
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "url": declared,
        "headline": "Flood in Lakeview",
        "datePublished": "2026-10-22T09:15:00Z",
        "articleBody": "Two people died in the Lakeview flood.",
        "author": {"name": "Jane Reporter"},
    }
    if kind == "jsonld":
        markup = '<script type="application/ld+json">' + json.dumps(news) + "</script>"
    else:
        payload = "8:" + json.dumps({"jsonLd": news}) + "\n"
        markup = "<script>self.__next_f.push(" + json.dumps([1, payload]) + ")</script>"
    return parse_discovery_article(
        markup,
        url=requested,
        document_url=requested,
        title="Index hint",
        publisher="Daily",
        retrieved_at=datetime(2026, 10, 23, tzinfo=UTC),
        indexed_at=None,
    )


@pytest.mark.parametrize("kind", ["jsonld", "flight"])
@pytest.mark.parametrize("reverse", [False, True])
def test_default_https_port_retains_owned_article_metadata(kind, reverse):
    explicit = URL.replace("publisher.example", "publisher.example:443")
    requested, declared = (URL, explicit) if reverse else (explicit, URL)
    article = parse(requested, declared, kind)
    assert article.source.published_at == datetime(2026, 10, 22, 9, 15, tzinfo=UTC)
    assert article.source.canonical_url == requested
    assert article.bylines == ("Jane Reporter",)
    assert article.text == "Two people died in the Lakeview flood."


@pytest.mark.parametrize("kind", ["jsonld", "flight"])
@pytest.mark.parametrize(
    "other",
    [
        URL.replace("publisher.example", "publisher.example:8443"),
        URL.replace("publisher.example", "other.example:443"),
        URL.replace("/report?", "/another?"),
        URL.replace("edition=one", "edition=two"),
        URL.replace("publisher.example", "user@publisher.example:443"),
    ],
)
def test_different_article_authorities_paths_and_queries_do_not_supply_clocks(
    kind, other
):
    article = parse(URL, other, kind)
    assert article.source.published_at is None
    assert article.bylines == ()


@pytest.mark.parametrize("kind", ["jsonld", "flight"])
@pytest.mark.parametrize("reverse", [False, True])
def test_explicit_empty_query_is_not_borrowed_from_a_queryless_page(kind, reverse):
    plain = "https://publisher.example/news/report"
    requested, declared = (plain, plain + "?") if reverse else (plain + "?", plain)
    article = parse(requested, declared, kind)
    assert article.source.published_at is None
