"""The page's main report owns its narrative; recommendation cards do not."""

import json
from datetime import UTC, datetime

import pytest

from disaster_monitor.infrastructure.news.discovery_parser import (
    parse_discovery_article,
)


def parse(markup):
    return parse_discovery_article(
        markup,
        url="https://publisher.example/main-report",
        title="Floods in Lakeview",
        publisher="Publisher",
        retrieved_at=datetime(2026, 10, 20, tzinfo=UTC),
        indexed_at=None,
    )


def test_explicit_body_marker_excludes_other_article_cards_and_preserves_caption():
    article = parse("""<main>
      <article><h1>Floods in Lakeview</h1>
        <div data-article-body="true"><p>Floods struck Lakeview on 14 October.</p>
          <figure><figcaption>Lakeview cleanup, 15 October.
          Photo: Agency</figcaption></figure>
          <p>Officials reported six deaths.</p></div>
      </article>
      <section><article><p>Wildfires spread across Highforest.</p></article>
        <article><p>A mine landslide killed nine people in Hilltown.</p></article>
      </section></main>""")
    assert "Officials reported six deaths" in article.text
    assert "Wildfires" not in article.text
    assert "landslide" not in article.text
    assert "15 October" not in article.text
    assert "Photo: Agency" in article.photograph_captions[0]


@pytest.mark.parametrize("recommendation_first", [False, True])
def test_unique_primary_heading_article_wins_without_merging_sibling_bodies(
    recommendation_first,
):
    primary = """<article><header><h1>Floods in Lakeview</h1></header>
      <p>Floods struck Lakeview on 14 October. Six people died.</p></article>"""
    recommendation = """<article><h2>Wildfire elsewhere</h2>
      <div itemprop="articleBody"><p>Wildfires struck Highforest. Nine died.</p></div>
      </article>"""
    contents = (
        recommendation + primary if recommendation_first else primary + recommendation
    )
    article = parse(f"<main>{contents}</main>")
    assert "Lakeview" in article.text
    assert "Highforest" not in article.text


def test_nested_article_card_is_not_part_of_parent_report():
    article = parse("""<main><article><h1>Floods in Lakeview</h1>
      <p>Floods struck Lakeview on 14 October.</p>
      <article><h2>Related story</h2><p>Wildfires struck Highforest.</p></article>
      <p>Six people died in the Lakeview flood.</p>
      </article></main>""")
    assert "Six people died" in article.text
    assert "Highforest" not in article.text


def test_multiple_unidentified_articles_are_ambiguous_instead_of_one_report():
    article = parse("""<main><article><p>Floods struck Lakeview.</p></article>
      <article><p>Wildfires struck Highforest.</p></article></main>""")
    assert article.text == ""


def test_one_unwrapped_semantic_body_remains_usable_without_an_article_element():
    article = parse("""<main><h1>Floods in Lakeview</h1>
      <div data-article-body="true">Floods struck Lakeview.<br>Six people died.</div>
      <article><p>Wildfires struck Highforest.</p></article></main>""")
    assert "Lakeview" in article.text and "Six people died" in article.text
    assert "Highforest" not in article.text


def test_structured_metadata_belongs_to_the_selected_page_not_the_first_related_story():
    objects = [
        {
            "@type": "NewsArticle",
            "url": "https://publisher.example/related",
            "datePublished": "2020-01-01T00:00:00Z",
            "articleBody": "Wildfires struck Highforest.",
        },
        {
            "@type": ["NewsArticle", "Article"],
            "mainEntityOfPage": {"@id": "https://publisher.example/main-report"},
            "datePublished": "2026-10-19T12:00:00Z",
            "articleBody": "Floods struck Lakeview.",
        },
    ]
    article = parse(
        f'<script type="application/ld+json">{json.dumps(objects)}</script>'
    )
    assert article.source.published_at == datetime(2026, 10, 19, 12, tzinfo=UTC)
    assert article.text == "Floods struck Lakeview."


def test_unmatched_multiple_structured_articles_do_not_supply_publication_or_body():
    objects = [
        {
            "@type": "NewsArticle",
            "datePublished": "2026-10-19T12:00:00Z",
            "articleBody": "Floods struck Lakeview.",
        },
        {
            "@type": "NewsArticle",
            "datePublished": "2026-10-18T12:00:00Z",
            "articleBody": "Wildfires struck Highforest.",
        },
    ]
    article = parse(
        f'<script type="application/ld+json">{json.dumps(objects)}</script>'
    )
    assert article.source.published_at is None
    assert article.text == ""


def test_publisher_headline_and_name_replace_an_index_hint():
    article = parse("""<head>
      <meta property="og:title" content="Publisher's flood report">
      <meta property="og:site_name" content="Regional Daily">
      <meta property="article:published_time" content="2026-10-19T12:00:00Z">
      </head><article><p>Floods struck Lakeview.</p></article>""")
    assert article.source.title == "Publisher's flood report"
    assert article.source.publisher == "Regional Daily"


def test_later_recommendation_metadata_cannot_replace_page_metadata():
    article = parse("""<head>
      <meta property="og:title" content="Publisher's flood report">
      <meta property="article:published_time" content="2026-10-19T12:00:00Z">
      </head><main><article><h1>Floods in Lakeview</h1><p>Six people died.</p></article>
      <article><meta property="og:title" content="Wildfire elsewhere">
      <meta property="article:published_time" content="2020-01-01T00:00:00Z">
      <p>Wildfires struck Highforest.</p></article></main>""")
    assert article.source.title == "Publisher's flood report"
    assert article.source.published_at == datetime(2026, 10, 19, 12, tzinfo=UTC)


def test_unmarked_report_uses_paragraphs_beside_its_publisher_headline():
    article = parse("""<meta property="og:title" content="Floods in Lakeview">
      <meta property="og:description" content="A short introduction cut midwor">
      <div><h1>Floods in Lakeview</h1><ul><li>Share this report</li></ul>
        <p>Floods struck <a href="/place">Lakeview</a> on 14 October.</p>
        <div><h1>A photograph of an older flood in Hilltown</h1>
          <p>Photo: Agency, 2020</p></div>
        <p>Officials reported six deaths and 22 injuries.</p>
        <aside><p>A wildfire killed nine people in Highforest.</p></aside>
      </div><div><h1>Other news</h1><p>More unrelated reporting.</p></div>""")
    assert article.text == (
        "Floods struck Lakeview on 14 October.\n"
        "Officials reported six deaths and 22 injuries."
    )


def test_structured_page_headline_can_anchor_an_unmarked_body_with_branded_og_title():
    metadata = {
        "@type": "NewsArticle",
        "url": "https://publisher.example/main-report",
        "headline": "Floods in Lakeview",
    }
    article = parse(f"""<meta property="og:title" content="Floods in Lakeview - Daily">
      <script type="application/ld+json">{json.dumps(metadata)}</script>
      <div><h1>Floods in <em>Lakeview</em></h1>
        <p>Floods struck Lakeview on 14 October.</p><p>Six people died.</p></div>""")
    assert "Six people died" in article.text


@pytest.mark.parametrize(
    "contents",
    [
        "<div><h1>Unrelated title</h1><p>Wrong report.</p><p>More text.</p></div>",
        "<div><h1>Floods in Lakeview</h1><p>Only a teaser.</p></div>",
        "<div><h1>Floods in Lakeview</h1><p><a href='/a'>Linked teaser one.</a></p>"
        "<p><a href='/b'>Linked teaser two.</a></p></div>",
        "<div hidden><h1>Floods in Lakeview</h1><p>Hidden report.</p>"
        "<p>More hidden reporting.</p></div>",
        "<div><h1>Floods in Lakeview</h1><p>One.</p><p>Two.</p></div>"
        "<div><h1>Floods in Lakeview</h1><p>Another.</p><p>Conflicting.</p></div>",
    ],
)
def test_unmarked_body_fails_closed_without_one_full_headline_owned_report(contents):
    article = parse(
        '<meta property="og:title" content="Floods in Lakeview">' + contents
    )
    assert article.text == ""


def test_index_title_alone_cannot_attribute_unmarked_page_paragraphs():
    article = parse("""<div><h1>Floods in Lakeview</h1>
      <p>Floods struck Lakeview.</p><p>Six people died.</p></div>""")
    assert article.text == ""


def test_unmarked_report_stops_at_the_next_sibling_heading():
    article = parse("""<meta property="og:title" content="Floods in Lakeview">
      <div><p>Unrelated introduction.</p><h1>Floods in Lakeview</h1>
        <p>Floods struck Lakeview.</p><p>Six people died.</p>
        <h2>Other news</h2><p>A wildfire killed nine people.</p></div>""")
    assert article.text == "Floods struck Lakeview.\nSix people died."


def test_unmarked_fallback_cannot_override_ambiguous_semantic_articles():
    article = parse("""<meta property="og:title" content="Floods in Lakeview">
      <article><p>Ambiguous report one.</p></article>
      <article><p>Ambiguous report two.</p></article>
      <div><h1>Floods in Lakeview</h1><p>One.</p><p>Two.</p></div>""")
    assert article.text == ""


@pytest.mark.parametrize(
    "surrounding",
    ["<div>" * 130, "<span></span>" * 10_001],
    ids=["depth-budget", "node-budget"],
)
def test_unmarked_fallback_rejects_documents_beyond_its_structural_budget(surrounding):
    article = parse(
        '<meta property="og:title" content="Floods in Lakeview">'
        + surrounding
        + "<div><h1>Floods in Lakeview</h1><p>One.</p><p>Two.</p></div>"
    )
    assert article.text == ""


@pytest.mark.parametrize("tag", ["p", "h2", "li"])
def test_fully_linked_recommendations_inside_a_report_are_not_narrative(tag):
    article = parse(f"""<article><h1>Floods in Lakeview</h1>
      <div itemprop="articleBody"><p>Floods struck Lakeview. Two people died.</p>
        <p><strong>Related News:</strong></p>
        <{tag}><a href="/elsewhere"><strong>A Highforest wildfire killed nine
        people.</strong></a></{tag}>
      </div></article>""")
    assert "Two people died" in article.text
    assert "Highforest" not in article.text


def test_an_inline_source_link_does_not_remove_the_reported_paragraph():
    article = parse("""<article><p>According to <a href="/source">the authority</a>,
      two people died in Lakeview's floods.</p></article>""")
    assert "two people died" in article.text
    assert "the authority" in article.text


def test_a_hidden_unlinked_child_does_not_turn_a_link_card_into_narrative():
    article = parse("""<article><h1>Floods in Lakeview</h1>
      <p>Floods struck Lakeview.</p>
      <p><span aria-hidden="true">New</span><a href="/elsewhere">A wildfire
      killed nine in Highforest.</a></p></article>""")
    assert "Lakeview" in article.text
    assert "Highforest" not in article.text


@pytest.mark.parametrize(
    "caption_class",
    [
        "caption",
        "image-caption",
        "photo-caption",
        "wp-caption-text",
    ],
)
def test_class_marked_photo_captions_are_retained_separately_from_narrative(
    caption_class,
):
    article = parse(f"""<article><h1>Floods in Lakeview</h1>
      <p>Floods struck Lakeview on 14 October.</p>
      <div class="{caption_class}"><p>Hilltown after a landslide in May 2019.
      Photo: Regional Agency</p></div>
      <p>Two people died in the Lakeview floods.</p></article>""")
    assert "Two people died" in article.text
    assert "2019" not in article.text and "Hilltown" not in article.text
    assert len(article.photograph_captions) == 1
    assert "May 2019" in article.photograph_captions[0]


def test_link_card_exclusion_preserves_nested_article_ownership():
    article = parse("""<article><h1>Floods in Lakeview</h1>
      <p>Floods struck Lakeview.</p>
      <article><p>Wildfires killed nine people in Highforest.</p></article>
      <p>Two people died in Lakeview.</p></article>""")
    assert "Two people died" in article.text
    assert "Highforest" not in article.text


def test_unmarked_headline_fallback_also_excludes_direct_class_marked_captions():
    article = parse("""<meta property="og:title" content="Floods in Lakeview">
      <div><h1>Floods in Lakeview</h1><p>Floods struck Lakeview.</p>
        <p class="photo-caption">Hilltown after a landslide in 2019.</p>
        <p>Two people died.</p></div>""")
    assert "Two people died" in article.text
    assert "Hilltown" not in article.text
    assert "2019" in article.photograph_captions[0]
