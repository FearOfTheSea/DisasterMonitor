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


@pytest.mark.parametrize("widget_class", ["also-read", "also_read", "story-also-read"])
@pytest.mark.parametrize("owned_body", [True, False])
def test_also_read_widget_does_not_own_its_unlinked_teaser(widget_class, owned_body):
    opening, closing = (
        ('<article><div itemprop="articleBody">', "</div></article>")
        if owned_body
        else ("<div>", "</div>")
    )
    article = parse(f'''<meta property="og:title" content="Floods in Lakeview">
        {opening}<h1>Floods in Lakeview</h1>
        <p>Floods struck Lakeview on 14 October. Six people died.</p>
        <div class="{widget_class}"><div class="title">
          <a href="https://publisher.example/other">A mine landslide killed nine.</a>
        </div><div class="description">Nine miners died in Highforest.</div>
        <div class="byline">Agency</div></div>
        <p>An engineer also read the river gauge. Twenty homes were damaged.</p>
        {closing}''')
    assert "Six people died" in article.text
    assert "engineer also read the river gauge" in article.text
    assert "Twenty homes were damaged" in article.text
    assert "Nine miners" not in article.text
    assert "Highforest" not in article.text


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


def test_articlebodycontent_owns_text_over_schema_with_embedded_recommendations():
    schema = {
        "@type": "NewsArticle",
        "url": "https://publisher.example/main-report",
        "headline": "Floods in Lakeview",
        "datePublished": "2026-10-20T10:00:00Z",
        "articleBody": "Floods killed six. A hurricane elsewhere killed nine.",
    }
    article = parse(
        '<script type="application/ld+json">' + json.dumps(schema) + "</script>"
        '<h1>Floods in Lakeview</h1><div class="articlebodycontent col-xl-9">'
        '<div class="schemaDiv"><p>Floods struck Lakeview. Six people died.</p>'
        '<div class="also-read print-hide"><div class="title">'
        '<a href="/other">A hurricane elsewhere killed nine.</a></div>'
        '<div class="description">Nine people died in Highforest.</div></div>'
        "<p>Twenty homes were damaged, officials said.</p></div></div>"
    )
    assert "Six people died" in article.text
    assert "Twenty homes were damaged" in article.text
    assert "hurricane" not in article.text
    assert "Highforest" not in article.text
    assert article.source.published_at == datetime(2026, 10, 20, 10, tzinfo=UTC)


@pytest.mark.parametrize("tag", ["strong", "b"])
@pytest.mark.parametrize("nested", [False, True])
def test_trailing_emphasized_linked_headline_is_not_the_paragraphs_fatality_account(
    tag,
    nested,
):
    headline = (
        "A landslide in Highforest <b>killed forty people.</b>"
        if nested
        else "A landslide in Highforest killed forty people."
    )
    article = parse(f"""<main><p>Floods struck Lakeview. Two people died.
      <{tag}><a href="/other">{headline}</a></{tag}>
      </p><p>Twenty homes were damaged.</p></main>""")
    assert "Two people died" in article.text
    assert "Twenty homes were damaged" in article.text
    assert "Highforest" not in article.text


@pytest.mark.parametrize(
    "paragraph",
    [
        '<strong><a href="/official">Two</a></strong> people died in the flood.',
        '<strong><a href="/official"><b>Two</b></a></strong> people died in the flood.',
        'The flood killed <strong><a href="/official">two people</a></strong>.',
        (
            'Officials said <strong><a href="/official">'
            "two people died in the Lakeview flood.</a></strong>"
        ),
        (
            'Officials <strong>said</strong> <strong><a href="/official">'
            "two people died in the Lakeview flood.</a></strong>"
        ),
        (
            'The report says <strong><a href="/official">'
            "two people died in the Lakeview flood.</a></strong> Rescue work continues."
        ),
        (
            'The flood killed two people, according to <strong><a href="/official">'
            "Dr. Alex Stone</a></strong>."
        ),
    ],
)
def test_linked_counts_names_and_inline_attributed_accounts_remain_narrative(paragraph):
    article = parse(f"<main><p>{paragraph}</p></main>")
    assert "two" in article.text.casefold()
    assert "died" in article.text or "killed" in article.text
    if "Alex Stone" in paragraph:
        assert "Alex Stone" in article.text


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


@pytest.mark.parametrize(
    "widget_class",
    ["author-box-related-entries", "related-stories", "recommended-content"],
)
def test_related_cards_with_unlinked_author_names_cannot_supply_article_claims(
    widget_class,
):
    article = parse(f"""<article><h1>Floods in Lakeview</h1>
      <div class="entry-content"><p>Floods struck Lakeview. Two people died.</p>
        <div class="{widget_class}"><ul><li>
          <div>Another writer</div><div><a href="/elsewhere">
            <span>Four deaths reported in a Highforest wildfire</span>
          </a></div></li></ul></div>
        <p>Rescue work continues in Lakeview.</p>
      </div></article>""")
    assert "Two people died" in article.text
    assert "Rescue work continues" in article.text
    assert "Highforest" not in article.text
    assert "Another writer" not in article.text


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


def test_read_content_body_keeps_narrative_beyond_the_meta_description():
    article = parse("""<meta property="og:description" content="Short damage summary.">
      <h1>Floods in Lakeview</h1><div class="read__content">
        <p>Floods struck Lakeview.</p><h2>Detailed local reporting</h2>
        <p>Rescuers inspected the river bridge. Two people died.</p>
      </div><section><p>A wildfire killed nine in Highforest.</p></section>""")
    assert "Rescuers inspected the river bridge" in article.text
    assert "Two people died" in article.text
    assert "Highforest" not in article.text


@pytest.mark.parametrize("wrapped_headline", [False, True])
def test_publisher_headline_can_own_one_article_class_paragraph_wrapper(
    wrapped_headline,
):
    headline = (
        '<div class="post-header"><h1>Floods in Lakeview</h1>'
        "<p>A short introduction.</p></div>"
        if wrapped_headline
        else "<h1>Floods in Lakeview</h1>"
    )
    article = parse(f"""<meta property="og:title" content="Floods in Lakeview">
      <meta property="og:description" content="Only the introduction.">
      <section><div>{headline}
        <div class="article"><p>Floods struck Lakeview on 14 October.</p>
          <p class="related-news"><a href="/other">A wildfire killed nine.</a></p>
          <p>Officials reported two deaths and three injuries.</p></div>
        <p>Unrelated material outside the article wrapper.</p></div></section>""")
    assert "two deaths" in article.text
    assert "three injuries" in article.text
    assert "wildfire" not in article.text
    assert "Unrelated material" not in article.text


@pytest.mark.parametrize(
    "markup",
    [
        '<h1>Floods in Lakeview</h1><div class="article"><p>Only a teaser.</p></div>',
        '<h1>Different report</h1><div class="article">'
        "<p>Wrong report.</p><p>More text.</p></div>",
        '<h1>Floods in Lakeview</h1><div class="article-card">'
        "<p>Wrong report.</p><p>More text.</p></div>",
        '<h1>Floods in Lakeview</h1><div class="article"><p>One.</p><p>Two.</p></div>'
        '<div class="article"><p>Another.</p><p>Conflicting.</p></div>',
    ],
)
def test_article_class_is_not_sufficient_without_one_full_headline_owned_body(markup):
    article = parse(
        '<meta property="og:title" content="Floods in Lakeview"><div>'
        + markup
        + "</div>"
    )
    assert article.text == ""


def test_nested_article_class_card_does_not_join_the_headline_owned_body():
    article = parse("""<meta property="og:title" content="Floods in Lakeview">
      <div><div><h1>Floods in Lakeview</h1></div><div class="article">
        <p>Floods struck Lakeview.</p>
        <div class="article"><p>A wildfire killed nine people.</p>
          <p>More unrelated reporting.</p></div>
        <p>Two people died in Lakeview.</p></div></div>""")
    assert "Two people died" in article.text
    assert "wildfire" not in article.text


def test_wrapped_index_headline_does_not_establish_publisher_body_ownership():
    article = parse("""<div><div><h1>Floods in Lakeview</h1></div>
      <div class="article"><p>Floods struck Lakeview.</p>
        <p>Two people died.</p></div></div>""")
    assert article.text == ""


def test_baca_juga_recommendations_do_not_become_an_owned_article_account():
    article = parse("""<article><h1>Floods in Lakeview</h1>
      <div data-article-body="true"><p>Floods struck Lakeview.</p>
        <p><strong>Baca juga: <a class="inner-link-baca-juga" href="/elsewhere">
        A wildfire killed nine people in Highforest.</a></strong></p>
        <p>Officials inspected the <a class="inner-link-tag" href="/tag/river">
        river bridge</a>. Two people died in the floods.</p>
      </div></article>""")
    assert "Highforest" not in article.text
    assert "river bridge" in article.text
    assert "Two people died in the floods" in article.text


def test_explicit_end_of_article_marker_excludes_later_appeals_inside_the_wrapper():
    article = parse("""<h1>Floods in Lakeview</h1><div class="read__content">
      <p>Floods struck Lakeview. Two people died.</p>
      <div id="EndOfArticle"></div>
      <p>Donate for wildfire victims in Highforest. Nine died there.</p>
    </div>""")
    assert "Two people died" in article.text
    assert "Highforest" not in article.text


def test_malformed_nested_navigation_anchors_do_not_make_the_report_all_linked():
    article = parse("""<nav><a href="/menu">Menu
      <a href="/next">Next</a></nav><article><h1>Floods in Lakeview</h1>
      <p>Floods struck Lakeview. Two people died.</p>
      <p><a href="/elsewhere">A wildfire killed nine in Highforest.</a></p>
    </article>""")
    assert "Two people died" in article.text
    assert "Highforest" not in article.text
