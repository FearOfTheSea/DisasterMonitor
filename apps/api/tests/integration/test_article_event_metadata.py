from datetime import UTC, datetime

from disaster_monitor.infrastructure.news.discovery_parser import (
    parse_discovery_article,
)
from disaster_monitor.infrastructure.news.reliefweb_discovery import _article

NOW = datetime(2026, 10, 18, 12, tzinfo=UTC)


def test_html_day_publication_and_paragraph_boundaries_are_retained():
    article = parse_discovery_article(
        """<script type="application/ld+json">{
      "@type":"NewsArticle", "datePublished":"2026-10-17"}</script>
      <article><h2>Flooding – Riverton</h2><p>Two people died.</p>
      <h2>Earthquake – Lakeview</h2><p>Five injured.</p></article>""",
        url="https://news.example/a",
        title="Regional situation update",
        publisher="Daily",
        retrieved_at=NOW,
        indexed_at=None,
    )
    assert article.source.publication_precision == "day"
    assert article.source.published_at == datetime(2026, 10, 17, tzinfo=UTC)
    assert "Flooding" in article.text and "Earthquake" in article.text
    assert "\n" in article.text


def test_reliefweb_retains_original_url_separately_from_article_identity():
    article = _article(
        {
            "fields": {
                "title": "Flood report",
                "url": "https://reliefweb.int/node/123",
                "origin": "https://www.ifrc.org/article/flood-report",
                "body": "Floods hit Riverton.",
                "date": {"original": "2026-10-17T00:00:00+00:00"},
            }
        },
        retrieved_at=NOW,
    )
    assert article.original_url == "https://www.ifrc.org/article/flood-report"
    assert article.source.canonical_url == "https://reliefweb.int/node/123"
    assert article.source.publication_precision == "day"


def test_parser_marks_sections_and_omits_hidden_republication_and_topic_tags():
    article = parse_discovery_article(
        """<article><h2>Flood recovery</h2>
      <p>Floods hit Riverton.</p><div class="entry-footer"><p>Hurricane Prep</p></div>
      <textarea><p>Earthquake in Lakeview</p></textarea></article>""",
        url="https://news.example/a",
        title="Regional update",
        publisher="Daily",
        retrieved_at=NOW,
        indexed_at=None,
    )
    assert "## Flood recovery" in article.text
    assert "Hurricane Prep" not in article.text
    assert "Earthquake in Lakeview" not in article.text


def test_main_article_body_is_used_when_publisher_has_no_article_element():
    from datetime import UTC, datetime

    from disaster_monitor.infrastructure.news.discovery_parser import (
        parse_discovery_article,
    )

    article = parse_discovery_article(
        "<main><h1>Flood update</h1><p>Floods hit Riverton on 9 October.</p>"
        "<aside><p>Unrelated floods in Lakeview.</p></aside></main>",
        url="https://publisher.example/report",
        title="Flood update",
        publisher="Daily",
        retrieved_at=datetime(2026, 10, 18, tzinfo=UTC),
        indexed_at=None,
    )
    assert "Floods hit Riverton on 9 October." in article.text
    assert "Lakeview" not in article.text
