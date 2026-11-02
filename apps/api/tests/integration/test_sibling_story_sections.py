"""A primary headline can own adjacent publisher story sections and a visible day."""

from datetime import UTC, datetime

from disaster_monitor.infrastructure.news.discovery_parser import (
    parse_discovery_article,
)

NOW = datetime(2026, 11, 1, tzinfo=UTC)
TITLE = "Families remember the Riverton flood dead"
FIRST = "Three residents died in the August flood along the river."
SECOND = "Families will gather next week to remember the victims."


def page(*, groups=None, clocks=None, heading=None):
    groups = groups or (
        f'<section class="story-section"><p><span>{FIRST}</span></p></section>'
        f'<section class="story-section"><p>{SECOND}</p></section>'
    )
    return f"""<html><head><meta property="og:type" content="article">
    <meta property="og:title" content="{TITLE}">
    <meta property="og:description" content="A short introduction."></head>
    <body><header><h1>Daily News</h1></header><main><div>
    <h1>{heading or TITLE}</h1><div>{clocks or ""}<div>{groups}</div></div>
    <article><h2>Different wildfire report</h2>
    <p>Nine people died in an unrelated wildfire.</p></article>
    <section class="related"><h1>{TITLE}</h1>
    <div class="updated-time">Published at : October 29, 2026</div></section>
    </div></main></body></html>"""


def parsed(html):
    return parse_discovery_article(
        html,
        url="https://daily.example/report",
        title=TITLE,
        publisher="Daily",
        retrieved_at=NOW,
        indexed_at=None,
    )


def test_adjacent_story_sections_belong_to_the_matching_main_headline():
    article = parsed(page())
    assert FIRST in article.text and SECOND in article.text
    assert "unrelated wildfire" not in article.text
    assert "Daily News" not in article.text


def test_main_publication_label_keeps_day_precision_without_inventing_a_zone():
    article = parsed(
        page(
            clocks="""
        <div class="updated-time"><span>Published at :</span> October 31, 2026</div>
        <div class="updated-time">Updated at : November 1, 2026 07:34</div>
        <div class="updated-time updated-time_location">Riverton</div>"""
        )
    )
    assert article.source.published_at == datetime(2026, 10, 31, tzinfo=UTC)
    assert article.source.publication_precision == "day"
    assert article.source.updated_at is None


def test_separate_story_groups_are_not_combined_under_one_headline():
    groups = (
        f'<div><section class="story-section"><p>{FIRST}</p></section></div>'
        f'<div><section class="story-section"><p>{SECOND}</p></section></div>'
    )
    assert FIRST not in parsed(page(groups=groups)).text


def test_intervening_heading_prevents_story_groups_from_becoming_one_report():
    groups = (
        f'<section class="story-section"><p>{FIRST}</p></section>'
        "<h2>Another occurrence</h2>"
        f'<section class="story-section"><p>{SECOND}</p></section>'
    )
    assert FIRST not in parsed(page(groups=groups)).text


def test_mismatched_primary_headline_cannot_supply_grouped_body_or_publication():
    article = parsed(
        page(
            heading="An unrelated primary headline",
            clocks='<div class="updated-time">Published at : October 31, 2026</div>',
        )
    )
    assert FIRST not in article.text
    assert article.source.published_at is None


def test_update_only_or_conflicting_publication_markers_remain_unknown():
    for clocks in (
        '<div class="updated-time">Updated at : October 31, 2026 07:34</div>',
        '<div class="updated-time">Published at : October 31, 2026</div>'
        '<div class="updated-time">Published at : October 30, 2026</div>',
    ):
        assert parsed(page(clocks=clocks)).source.published_at is None
