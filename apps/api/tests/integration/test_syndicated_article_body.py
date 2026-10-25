"""Short syndicated reports retain their body without borrowing adjacent cards."""

from datetime import UTC, datetime

import pytest

from disaster_monitor.infrastructure.news.discovery_parser import (
    parse_discovery_article,
)


def parse(markup):
    return parse_discovery_article(
        markup,
        url="https://publisher.example/local-report",
        title="Local report",
        publisher="Daily",
        retrieved_at=datetime(2026, 10, 24, tzinfo=UTC),
        indexed_at=None,
    )


@pytest.mark.parametrize("marker", ["q-content__info", "post_content"])
def test_syndicated_body_outside_article_tags_remains_owned_among_article_cards(marker):
    article = parse(f"""<meta property="og:description" content="A short rain summary.">
      <div class="q-content"><h1>Local report</h1>
        <div class="{marker}">
          <p>A man was found after heavy rain.</p>
          <p>He tried to cross a flooded road and was swept away.</p>
          <div class="related"><article><p>A wildfire killed nine elsewhere.</p>
            </article></div>
          <p>Rescuers recovered his body near the bridge.</p>
          <p>The full report: <a href="https://regional.example/report">Regional</a></p>
        </div></div>
      <section><article><h2>Other report</h2><p>A landslide killed forty.</p>
        </article></section>""")
    assert "flooded road and was swept away" in article.text
    assert "recovered his body" in article.text
    assert "wildfire" not in article.text
    assert "landslide" not in article.text


@pytest.mark.parametrize("suffix", ["-card", "-related", "-teaser"])
@pytest.mark.parametrize("marker", ["q-content__info", "post_content"])
def test_body_marker_does_not_match_a_longer_widget_class(suffix, marker):
    article = parse(f"""<article><p>Unidentified report one.</p></article>
      <article><p>Unidentified report two.</p></article>
      <div class="{marker}{suffix}">
        <p>Unrelated floods killed nine.</p></div>""")
    assert article.text == ""


@pytest.mark.parametrize("marker", ["q-content__info", "post_content"])
def test_two_unowned_syndicated_bodies_remain_ambiguous(marker):
    article = parse(f"""<div class="{marker}"><p>Floods killed two.</p></div>
      <div class="{marker}"><p>A landslide killed nine.</p></div>""")
    assert article.text == ""


def test_owned_paragraphs_keep_readable_entities_and_separate_local_accounts():
    article = parse("""<h1>Local report</h1>
      <div class="post_content jl_content">
        <p>El r&iacute;o se desbord&oacute; e inund&oacute; varias viviendas.</p>
        <p>Una mujer falleci&oacute; en la carretera inundada.</p>
      </div>
      <article><h2>Other report</h2><p>A fire killed nine elsewhere.</p></article>
      <article><h2>More news</h2><p>An earthquake injured ten.</p></article>""")
    assert article.text.splitlines() == [
        "El río se desbordó e inundó varias viviendas.",
        "Una mujer falleció en la carretera inundada.",
    ]
