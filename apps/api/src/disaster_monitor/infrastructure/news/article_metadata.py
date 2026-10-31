"""Own primary-article metadata without borrowing from other page content."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlsplit, urlunsplit


def page_identities(url: str, document_url: str | None) -> set[str]:
    return {
        identity
        for value in (url, document_url)
        if value and (identity := _page_identity(value)) is not None
    }


def _page_identity(value: str) -> str | None:
    """Compare HTTPS page identity without changing retained source URLs."""
    try:
        parts = urlsplit(value)
        if (
            parts.scheme != "https"
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
        ):
            return None
        host = parts.hostname
        authority = f"[{host}]" if ":" in host else host
        if parts.port not in (None, 443):
            authority += f":{parts.port}"
        identity = urlunsplit((parts.scheme, authority, parts.path, parts.query, ""))
        if not parts.query and "?" in value.split("#", 1)[0]:
            identity += "?"
        return identity
    except ValueError:
        return None


def _article_identity_values(article: dict[str, Any]) -> tuple[str, ...]:
    result = []
    for value in (
        article.get("url"),
        article.get("@id"),
        article.get("mainEntityOfPage"),
    ):
        if isinstance(value, dict):
            value = value.get("@id") or value.get("url")
        if isinstance(value, str) and value.strip():
            result.append(value)
    return tuple(result)


def article_identities(article: dict[str, Any]) -> set[str]:
    result = set()
    for value in _article_identity_values(article):
        if value.startswith("https://"):
            identity = _page_identity(value)
            if identity is not None:
                result.add(identity)
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
        if len(dated) > 1 and len(headlines) <= 1:
            clocks = {article["datePublished"].strip() for article in dated}
            if len(clocks) == 1:
                return agreeing_article_metadata(dated)
    if len(articles) == 1 and not _article_identity_values(articles[0]):
        return articles[0]
    return {}


def agreeing_article_metadata(articles: list[dict[str, Any]]) -> dict[str, Any]:
    """Retain owned, agreeing assertions without selecting a conflicting template."""
    result: dict[str, Any] = {}
    keys = set().union(*(article.keys() for article in articles))
    for key in keys - {"author"}:
        values = {
            json.dumps(article[key], sort_keys=True, ensure_ascii=False): article[key]
            for article in articles
            if key in article and article[key] not in (None, "")
        }
        if len(values) == 1:
            result[key] = next(iter(values.values()))
    # A schema can use id or url for the same named author. Preserve every
    # explicit byline from these owned objects; names do not prove independence.
    names = {name for article in articles for name in article_bylines(article, [])}
    result["author"] = sorted(names, key=lambda name: (name.casefold(), name))[:32]
    # Equivalent headline whitespace/case was already checked across all objects.
    headlines = sorted(
        article["headline"]
        for article in articles
        if isinstance(article.get("headline"), str) and article["headline"].strip()
    )
    if headlines:
        result["headline"] = headlines[0]
    result["datePublished"] = articles[0]["datePublished"].strip()
    return result


def article_bylines(news: dict[str, Any], page_authors: list[str]) -> tuple[str, ...]:
    """Retain explicit names without treating a producer as a specific report."""
    authors = news.get("author")
    authors = authors if isinstance(authors, list) else [authors]
    names = [a.get("name") if isinstance(a, dict) else a for a in authors[:32]]
    result: dict[str, str] = {}
    for value in [*names, *page_authors[:32]]:
        if not isinstance(value, str):
            continue
        name = " ".join(value.split())
        if not name or len(name) > 256 or name.startswith(("https://", "http://")):
            continue
        result.setdefault(name.casefold(), name)
    return tuple(result.values())
