"""Publisher body containers retain prose independently of paragraph markup."""

from datetime import UTC, datetime

import pytest

from disaster_monitor.infrastructure.news.discovery_parser import (
    parse_discovery_article,
)

NOW = datetime(2026, 11, 4, tzinfo=UTC)
TEXT = "Original reporting about the river. A resident describes the flooding."


def parse(body):
    return parse_discovery_article(
        '<meta property="og:title" content="River report">' + body,
        url="https://daily.example/report",
        title="River report",
        publisher="Daily",
        retrieved_at=NOW,
        indexed_at=None,
    )


@pytest.mark.parametrize(
    "container",
    [
        '<div id="articleContent">{}</div>',
        '<div class="elementor-widget-theme-post-content">{}</div>',
        "<article>{}</article>",
    ],
)
def test_explicit_body_keeps_unwrapped_prose_and_excludes_widgets(container):
    body = container.format(
        TEXT + "<aside>Unrelated earthquake</aside>"
        '<div class="related">An unrelated wildfire killed nine people.</div>'
        "<p>Reporter: A correspondent.</p>"
    )
    article = parse(body)
    assert TEXT in article.text
    assert "Reporter: A correspondent." in article.text
    assert "Unrelated" not in article.text and "unrelated" not in article.text


def test_multiple_unidentified_articles_remain_separate():
    assert not parse(
        f"<article>{TEXT}</article><article>Different news.</article>"
    ).text


def test_body_identifier_does_not_match_a_partial_name():
    assert not parse(f'<div id="articleContentRecommendations">{TEXT}</div>').text


def test_unmarked_nested_widgets_and_link_cards_do_not_become_direct_article_prose():
    article = parse(
        f"<article>{TEXT}<div>Unrelated earthquake killed nine people.</div>"
        '<a href="/other">Unrelated wildfire killed two people.</a></article>'
    )
    assert TEXT in article.text
    assert "Unrelated" not in article.text
