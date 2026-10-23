"""Identify a primary article without borrowing clocks from other page content."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urldefrag


def page_identities(url: str, document_url: str | None) -> set[str]:
    return {urldefrag(value)[0] for value in (url, document_url) if value}


def article_identities(article: dict[str, Any]) -> set[str]:
    result = set()
    for value in (
        article.get("url"),
        article.get("@id"),
        article.get("mainEntityOfPage"),
    ):
        if isinstance(value, dict):
            value = value.get("@id") or value.get("url")
        if isinstance(value, str) and value.startswith("https://"):
            try:
                result.add(urldefrag(value)[0])
            except ValueError:
                pass
    return result


def primary_news(
    objects: list[dict[str, Any]], url: str, document_url: str | None = None
) -> dict[str, Any]:
    articles = []
    seen_articles: set[str] = set()
    for obj in objects:
        kind = obj.get("@type")
        kinds = kind if isinstance(kind, list) else [kind]
        if any(k in ("NewsArticle", "Article", "ReportageNewsArticle") for k in kinds):
            identity = json.dumps(obj, sort_keys=True, ensure_ascii=False)
            if identity not in seen_articles:
                seen_articles.add(identity)
                articles.append(obj)

    page_urls = page_identities(url, document_url)
    matching = [
        article for article in articles if page_urls & article_identities(article)
    ]
    if len(matching) == 1:
        return matching[0]
    if len(matching) > 1:
        # Some publishers emit a complete primary article and a second undated
        # teaser template with the same page identity. Prefer the uniquely dated
        # object only when all supplied headlines agree; conflicting clocks or
        # distinct articles remain unresolved rather than depending on order.
        dated = [
            article
            for article in matching
            if isinstance(article.get("datePublished"), str)
            and article["datePublished"].strip()
        ]
        headlines = {
            " ".join(article["headline"].split()).casefold()
            for article in matching
            if isinstance(article.get("headline"), str) and article["headline"].strip()
        }
        if len(dated) == 1 and len(headlines) <= 1:
            return dated[0]
    if len(articles) == 1 and not article_identities(articles[0]):
        return articles[0]
    return {}
