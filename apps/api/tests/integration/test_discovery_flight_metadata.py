"""Only explicitly identified article metadata in inert Flight data owns clocks."""

import json
from datetime import UTC, datetime

import pytest

from disaster_monitor.infrastructure.news.discovery_parser import (
    parse_discovery_article,
)

URL = "https://publisher.example/news/flood"
NEWS = {
    "@context": "https://schema.org",
    "@type": "NewsArticle",
    "mainEntityOfPage": URL,
    "headline": "Flood kills two in Lakeview",
    "datePublished": "2026-10-22T10:16:00+0300",
    "dateModified": "2026-10-23T09:00:00+0300",
    "articleBody": "Two people died in the Lakeview flood.",
}


def push(payload, channel=1):
    return "self.__next_f.push(" + json.dumps([channel, payload]) + ")"


def script(value):
    return "<script>" + value + "</script>"


def record(news):
    tree = ["$", "div", None, {"children": ["$", "$La9", None, {"jsonLd": news}]}]
    return "8:" + json.dumps(tree, ensure_ascii=False) + "\n"


def parse(html, **kwargs):
    return parse_discovery_article(
        html,
        url=URL,
        title="Index hint",
        publisher="Daily",
        retrieved_at=datetime(2026, 10, 23, 12, tzinfo=UTC),
        indexed_at=None,
        **kwargs,
    )


def test_flight_primary_article_retains_explicit_publication_and_separate_update():
    article = parse(script(push(record(NEWS))))
    assert article.source.published_at == datetime(2026, 10, 22, 7, 16, tzinfo=UTC)
    assert article.source.updated_at == datetime(2026, 10, 23, 6, tzinfo=UTC)
    assert article.source.title == NEWS["headline"]
    assert article.text == NEWS["articleBody"]
    assert article.event_time is None


def test_flight_chunks_can_split_records_and_keep_unicode_line_separators():
    news = dict(NEWS, headline="Flood\u2028kills two in Lakeview")
    data = record(news)
    middle = data.index("datePublished") + 5
    html = script("(self.__next_f=self.__next_f||[]).push([0]);" + push(None, 2))
    html += script(push(data[:middle])) + script(push(data[middle:]))
    article = parse(html)
    assert article.source.published_at is not None
    assert article.source.title == news["headline"]


def test_flight_metadata_matches_the_admitted_redirect_identity():
    redirected = "https://publisher.example/news/flood-corrected"
    article = parse(
        script(push(record(dict(NEWS, mainEntityOfPage={"@id": redirected})))),
        document_url=redirected,
    )
    assert article.source.published_at is not None
    assert article.source.canonical_url == URL


@pytest.mark.parametrize(
    "changes",
    [
        {"mainEntityOfPage": "https://publisher.example/related"},
        {"mainEntityOfPage": None},
        {"@context": None},
        {"@context": "https://unrelated.example/schema"},
        {"@type": "ImageObject"},
    ],
)
def test_flight_widgets_and_unidentified_objects_cannot_supply_article_metadata(
    changes,
):
    article = parse(script(push(record(dict(NEWS, **changes)))))
    assert article.source.published_at is None
    assert not article.text


@pytest.mark.parametrize(
    "wrap",
    [
        lambda call: "if (false) {" + call + "}",
        lambda call: call + ";fetch('https://elsewhere.example/')",
        lambda call: "const example = " + json.dumps(call),
        lambda call: call.replace('[1, "', '[1, run("', 1),
    ],
)
def test_arbitrary_javascript_is_never_interpreted_as_flight_metadata(wrap):
    article = parse(script(wrap(push(record(NEWS)))))
    assert article.source.published_at is None
    assert not article.text


def test_unavailable_or_malformed_flight_segments_do_not_join_into_valid_metadata():
    data = record(NEWS)
    for middle in (push("binary", 3), "self.__next_f.push([1, invalid])"):
        article = parse(
            script(push(data[:40])) + script(middle) + script(push(data[40:]))
        )
        assert article.source.published_at is None


def test_conflicting_plain_and_flight_primary_publications_remain_unresolved():
    html = '<script type="application/ld+json">' + json.dumps(NEWS) + "</script>"
    html += script(push(record(dict(NEWS, datePublished="2026-10-20T10:00:00Z"))))
    assert parse(html).source.published_at is None


def test_flight_data_remains_hidden_and_does_not_replace_visible_article_body():
    html = script(push(record(NEWS)))
    html += (
        "<article><h1>Flood kills two in Lakeview</h1>"
        "<p>Roads remain closed.</p></article>"
    )
    article = parse(html)
    assert article.source.published_at is not None
    assert "Roads remain closed." in article.text
    assert "Two people died" not in article.text
    assert "jsonLd" not in article.text


def test_flight_update_photo_and_page_clocks_are_not_publication_or_onset():
    news = dict(
        NEWS, datePublished=None, image={"datePublished": "2020-01-01T00:00:00Z"}
    )
    article = parse(script(push(record({"pageDate": "2026-10-23", "jsonLd": news}))))
    assert article.source.published_at is None
    assert article.source.updated_at is not None
    assert article.event_time is None


def test_oversize_flight_data_is_bounded_without_borrowing_a_partial_stream():
    article = parse(script(push(record(NEWS))) + script(push("x" * 1_000_001)))
    assert article.source.published_at is None


def test_deep_flight_data_is_bounded_without_discarding_separate_plain_metadata():
    nested = record(NEWS)
    html = script(push("8:" + "[" * 1000 + "null" + "]" * 1000 + "\n" + nested))
    html += '<script type="application/ld+json">' + json.dumps(NEWS) + "</script>"
    assert parse(html).source.published_at is not None


def test_length_framed_text_cannot_impersonate_a_metadata_record():
    quoted = "A quoted example with café and 雨:\n" + record(NEWS)
    data = "a:T" + format(len(quoted.encode("utf-8")), "x") + "," + quoted
    assert parse(script(push(data))).source.published_at is None
    # UTF-8 byte length, not character length, locates the following real record.
    assert parse(script(push(data + record(NEWS)))).source.published_at is not None


@pytest.mark.parametrize(
    "payload", ["a:Tffff,short\n", "a:Zunknown\n", "not a record\n"]
)
def test_invalid_flight_framing_cannot_be_skipped_to_find_later_metadata(payload):
    assert parse(script(push(payload + record(NEWS)))).source.published_at is None


def test_error_and_import_records_cannot_become_article_metadata():
    for tag in ("E", "I", "D"):
        assert (
            parse(
                script(push("a:" + tag + json.dumps(NEWS) + "\n"))
            ).source.published_at
            is None
        )


@pytest.mark.parametrize(
    "attrs",
    ['src="https://elsewhere.example/script.js"', 'type="application/json"'],
)
def test_noninline_or_nonjavascript_script_data_is_not_a_flight_stream(attrs):
    html = "<script " + attrs + ">" + push(record(NEWS)) + "</script>"
    assert parse(html).source.published_at is None
