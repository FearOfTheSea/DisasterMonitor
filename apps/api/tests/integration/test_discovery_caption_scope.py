"""HTML photograph captions retain source wording outside occurrence narrative."""

from datetime import UTC, datetime

from disaster_monitor.infrastructure.news.discovery_parser import (
    parse_discovery_article,
)


def test_caption_date_is_retained_without_becoming_part_of_occurrence_narrative():
    article = parse_discovery_article(
        """<meta property="article:published_time" content="2026-10-19T15:30:00Z">
        <article><div itemprop="articleBody"><p>Floods hit Lakeview on 9 October.</p>
        <figure><img src="/photo.jpg"><figcaption>Residents after floods caused
        damage in Lakeview, 15 October 2026. Photo: Regional Agency
        </figcaption></figure>
        <p>Two people died.</p></div></article>""",
        url="https://publisher.example/story",
        title="Floods in Lakeview",
        publisher="Publisher",
        retrieved_at=datetime(2026, 10, 19, tzinfo=UTC),
        indexed_at=None,
    )
    assert "15 October" not in article.text
    assert "Two people died" in article.text
    assert "9 October" in article.text
    assert len(article.photograph_captions) == 1
    assert "15 October 2026" in article.photograph_captions[0]
    assert "Regional Agency" in article.photograph_captions[0]
