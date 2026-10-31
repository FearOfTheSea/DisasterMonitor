"""Publisher-matched sibling headings own one following article in the same main."""

from datetime import UTC, datetime

import pytest

from disaster_monitor.infrastructure.news.discovery_parser import (
    parse_discovery_article,
)

HEAD = (
    '<meta property="og:type" content="article"><meta proper'
    'ty="og:title" content="Community recovery"><meta proper'
    'ty="og:description" content="The local newspaper">'
)
BODY = (
    "<p>A landslide killed three residents last spring.</p><"
    "p>Survivors received assistance.</p>"
)
CARD = (
    "<article><h2>Different occurrence</h2><p>A flood killed"
    " nine people elsewhere.</p></article>"
)


def parse(html):
    return parse_discovery_article(
        HEAD + html,
        url="https://local.example/news",
        title="Index title",
        publisher="Local paper",
        retrieved_at=datetime(2026, 10, 1, tzinfo=UTC),
        indexed_at=None,
    )


@pytest.mark.parametrize(
    "heading",
    [
        "<h1>Community recovery</h1>",
        "<header><h1>Community recovery</h1><p>By local reporter</p></header>",
        "<header><h1>Community <em>recovery</em></h1></header>",
    ],
)
def test_matching_primary_heading_keeps_its_body_without_related_cards(heading):
    article = parse(
        "<main>" + heading + "<article>" + BODY + "</article>" + CARD + "</main>"
    )
    assert "landslide killed three" in article.text
    assert "Survivors received assistance" in article.text
    assert "flood killed nine" not in article.text
    assert "Different occurrence" not in article.text
    assert article.source.title == "Community recovery"


@pytest.mark.parametrize(
    "html",
    [
        "<h1>Community recovery</h1><main><article>"
        + BODY
        + "</article>"
        + CARD
        + "</main>",
        "<main><h1>Unrelated heading</h1><article>"
        + BODY
        + "</article>"
        + CARD
        + "</main>",
        "<main><header><h1>Community recovery</h1></header></main><main><article>"
        + BODY
        + "</article>"
        + CARD
        + "</main>",
        "<main><aside><h1>Community recovery</h1></aside><article>"
        + BODY
        + "</article>"
        + CARD
        + "</main>",
        "<main><h1>Community recovery</h1><article>"
        + BODY
        + "</article><h1>Community recovery</h1>"
        + CARD
        + "</main>",
    ],
)
def test_unmatched_outside_main_hidden_cross_main_or_ambiguous_headings_fail_closed(
    html,
):
    assert "landslide killed three" not in parse(html).text


def test_an_earlier_unidentified_article_does_not_steal_the_matched_heading():
    article = parse(
        "<main>"
        + CARD
        + "<header><h1>Community recovery</h1></header><article>"
        + BODY
        + "</article>"
        + CARD
        + "</main>"
    )
    assert "landslide killed three" in article.text
    assert "flood killed nine" not in article.text


def test_the_next_article_outside_main_does_not_acquire_a_heading_owner():
    article = parse(
        "<main><h1>Community recovery</h1></main><article>" + BODY + "</article>" + CARD
    )
    assert "landslide killed three" not in article.text


def test_a_topic_index_cannot_assign_a_card_by_matching_page_title():
    page = HEAD.replace('<meta property="og:type" content="article">', "")
    article = parse_discovery_article(
        page
        + "<main><h1>Community recovery</h1><article>"
        + BODY
        + "</article>"
        + CARD
        + "</main>",
        url="https://local.example/news",
        title="Index title",
        publisher="Local paper",
        retrieved_at=datetime(2026, 10, 1, tzinfo=UTC),
        indexed_at=None,
    )
    assert "landslide killed three" not in article.text


def test_hidden_article_cards_do_not_acquire_the_pending_heading():
    article = parse(
        "<main><header><h1>Community recovery</h1></header><aside>"
        + CARD
        + "</aside><article>"
        + BODY
        + "</article>"
        + CARD
        + "</main>"
    )
    assert "landslide killed three" in article.text
    assert "flood killed nine" not in article.text


def test_a_new_unmatched_heading_expires_the_previous_pending_owner():
    article = parse(
        "<main><h1>Community recovery</h1><h1>Other topic</h1><article>"
        + BODY
        + "</article>"
        + CARD
        + "</main>"
    )
    assert "landslide killed three" not in article.text


def test_an_unmatched_related_article_heading_cannot_override_the_publisher_heading():
    related = CARD.replace("<h2>", "<h1>").replace("</h2>", "</h1>")
    article = parse(
        "<main><h1>Community recovery</h1><article>"
        + BODY
        + "</article>"
        + related
        + "</main>"
    )
    assert "landslide killed three" in article.text
    assert "flood killed nine" not in article.text


def test_an_intervening_section_heading_breaks_the_pending_article_owner():
    article = parse(
        "<main><h1>Community recovery</h1><h2>Other reports</h2><article>"
        + BODY
        + "</article>"
        + CARD
        + "</main>"
    )
    assert "landslide killed three" not in article.text
