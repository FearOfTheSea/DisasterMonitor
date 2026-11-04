"""One metered Google metadata operation per durable page."""

import json
import re
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode, urljoin

import httpx
from pydantic import TypeAdapter

from disaster_monitor.domain.collection import (
    CollectionPage,
    CollectionPartition,
    CollectionProviderError,
)
from disaster_monitor.domain.collection_retrieval_priority import (
    citation_resolution_priority,
)
from disaster_monitor.domain.disaster_types import Country
from disaster_monitor.domain.news import NewsFeedItem
from disaster_monitor.infrastructure.news.collection_http import CollectionHttp
from disaster_monitor.infrastructure.news.google_news_metadata import (
    ARTICLE_PREFIX,
    GoogleArticleMetadata,
    article_parameters,
    feed_articles,
    google_article_id,
    publisher_destination,
    resolution_form,
    validate_destination,
)
from disaster_monitor.infrastructure.news.public_documents import public_document_host

_ARTICLE = TypeAdapter(GoogleArticleMetadata)
_REDIRECTS = (301, 302, 303, 307, 308)
_MARKETS = {
    "en-US": ("en-US", "US", "US:en"),
    "en-IN": ("en-IN", "IN", "IN:en"),
    "fr": ("fr", "FR", "FR:fr"),
    "es": ("es", "ES", "ES:es"),
    "tr": ("tr", "TR", "TR:tr"),
    "id": ("id", "ID", "ID:id"),
    "ar": ("ar", "SA", "SA:ar"),
}
_SEEDS = {
    "en-US": (
        "earthquake",
        "earthquake killed",
        "flood",
        "flood killed",
        "wildfire",
        "wildfire killed",
        "landslide",
        "landslide killed",
        "cyclone",
        "cyclone killed",
        "volcanic eruption",
        "volcanic eruption deaths",
        "drought",
        "drought deaths",
    ),
    "en-IN": ("landslide", "landslide killed"),
    "fr": ("glissement de terrain", "éboulement morts"),
    "es": ("inundaciones", "crecida muere"),
    "tr": ("deprem", "heyelan öldü"),
    "id": ("longsor", "longsor tewas"),
    "ar": ("زلزال", "انهيار أرضي قتلى"),
}
_QUERIES = {
    market + "|" + query: (query, _MARKETS[market])
    for market, queries in _SEEDS.items()
    for query in queries
}
_COUNTRY_HAZARDS = (
    "earthquake OR flood OR wildfire OR landslide OR cyclone OR "
    '"volcanic eruption" OR drought'
)


def _geographic_queries(
    countries: tuple[Country, ...],
) -> dict[str, tuple[str, tuple[str, str, str]]]:
    queries = {}
    for country in sorted(countries, key=lambda item: item.alpha3_code):
        name = country.canonical_name
        if (
            not re.fullmatch(r"[A-Z]{3}", country.alpha3_code)
            or not name
            or len(name) > 200
            or any(char in name for char in ('"', "\\", "\n", "\r"))
        ):
            raise ValueError("Country metadata cannot form a Google news query.")
        # Include the catalog wording in the durable key: a later catalog rename
        # must not silently change an already issued query's meaning.
        key = f"en-US|country:{country.alpha3_code}:{name}"
        queries[key] = (f'"{name}" ({_COUNTRY_HAZARDS})', _MARKETS["en-US"])
    return queries


class GoogleNewsCollectionProvider:
    source_id = "google-rss-discovery"
    supports_time_filter = True
    supports_alternates = True

    def __init__(
        self,
        *,
        countries: Callable[[], tuple[Country, ...]] = lambda: (),
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 15,
        minimum_interval: float = 2,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._countries = countries
        self._queries = dict(_QUERIES)
        self._http = CollectionHttp(
            client=client,
            timeout_seconds=timeout_seconds,
            minimum_interval=minimum_interval,
        )
        self._clock = clock

    @property
    def queries(self) -> tuple[str, ...]:
        geographic = _geographic_queries(self._countries())
        # Catalog refreshes extend future plans. Keep literal previously issued
        # keys resolvable without changing their original country wording.
        self._queries.update(geographic)
        return (*_QUERIES, *geographic)

    def _query(self, key: str) -> tuple[str, tuple[str, str, str]] | None:
        if key not in self._queries:
            # A reopened journal can claim an issued root before a new scan has
            # requested a plan from this provider instance.
            self._queries.update(_geographic_queries(self._countries()))
        return self._queries.get(key)

    async def fetch_page(self, partition: CollectionPartition) -> CollectionPage:
        if partition.query.startswith(ARTICLE_PREFIX):
            return await self._resolve(partition)
        if partition.cursor:
            raise CollectionProviderError(
                "invalid_response", "Google RSS continuation or query is invalid."
            )
        if partition.alternate_for:
            query = partition.query
            if (
                not public_document_host(partition.alternate_for)
                or not re.fullmatch(r"[\w’'\" -]{1,300}", query)
                or len(query.split()) > 32
                or not any(char.isalnum() for char in query)
            ):
                raise CollectionProviderError(
                    "invalid_response", "Google alternate query is invalid."
                )
            locale = _MARKETS["en-US"]
        elif (route := self._query(partition.query)) is not None:
            query, locale = route
        else:
            raise CollectionProviderError(
                "invalid_response", "Google RSS continuation or query is invalid."
            )
        end = min(partition.end, self._clock())
        # Date hints deliberately overlap day boundaries. Publisher-original time
        # and each viewer's exact frozen interval remain authoritative later.
        dated = (
            query
            + " after:"
            + (partition.start - timedelta(days=1)).date().isoformat()
            + " before:"
            + (end + timedelta(days=1)).date().isoformat()
        )
        response = await self._http.get_bytes(
            "https://news.google.com/rss/search",
            {"q": dated, "hl": locale[0], "gl": locale[1], "ceid": locale[2]},
        )
        children = tuple(
            replace(
                partition,
                query=ARTICLE_PREFIX + article.identity,
                cursor=self._cursor(
                    {
                        "article": json.loads(_ARTICLE.dump_json(article)),
                        "stage": "page",
                        "redirects": 0,
                    }
                ),
                depth=partition.depth + 1,
                priority=0,
                defer_initial_request=True,
                shared_resource=partition.alternate_for is None,
            )
            for article in sorted(
                feed_articles(response.body, locale),
                key=lambda item: (
                    citation_resolution_priority(item.title),
                    item.indexed_at or datetime.min.replace(tzinfo=UTC),
                ),
                reverse=True,
            )
        )
        # Stable hint ordering retains every result, including unfamiliar titles.
        # Recency breaks equal-strength ties; it never supplies publication facts.
        # The journal still balances query families and publication windows.
        # Resolve unstarted citations after initial index coverage. A successful
        # public-page step becomes a normal-priority journal continuation, so its
        # short-lived public metadata is used before other unstarted citations.
        return CollectionPage(
            children=children,
            saturated=True,
            notices=(
                "Google RSS is a limited index snapshot, not exhaustive reporting. "
                "Index dates and titles are not publisher evidence.",
            ),
            requested_start=partition.start,
            requested_end=end,
        )

    @staticmethod
    def _cursor(value: dict[str, Any]) -> str:
        return json.dumps(value, separators=(",", ":"))

    def _state(
        self, partition: CollectionPartition
    ) -> tuple[dict[str, Any], GoogleArticleMetadata]:
        try:
            if (
                partition.depth < 1
                or not partition.cursor
                or len(partition.cursor) > 16_384
            ):
                raise ValueError("Invalid metadata continuation")
            state = json.loads(partition.cursor)
            article = _ARTICLE.validate_python(state["article"])
            if partition.query != ARTICLE_PREFIX + article.identity or state[
                "stage"
            ] not in ("page", "rpc"):
                raise ValueError("Mismatched continuation")
            redirects = state["redirects"]
            if (
                isinstance(redirects, bool)
                or not isinstance(redirects, int)
                or not 0 <= redirects <= 3
            ):
                raise ValueError("Unbounded redirects")
            if state["stage"] == "rpc":
                if (
                    not isinstance(state.get("timestamp"), int)
                    or isinstance(state["timestamp"], bool)
                    or state["timestamp"] < 0
                ):
                    raise ValueError("Invalid metadata timestamp")
                if (
                    not isinstance(state.get("signature"), str)
                    or not 1 <= len(state["signature"]) <= 4096
                ):
                    raise ValueError("Invalid metadata signature")
                captured = datetime.fromisoformat(state["captured"])
                if captured.tzinfo is None:
                    raise ValueError("Missing capture timezone")
                # Reopening a paused pass refreshes expired public page metadata,
                # spending a new metered request rather than fabricating a token.
                if not -60 <= (self._clock() - captured).total_seconds() <= 120:
                    state.update(stage="page", redirects=0)
                    state.pop("page_url", None)
            return state, article
        except (ValueError, TypeError, KeyError, AttributeError) as error:
            raise CollectionProviderError(
                "invalid_response", "Google metadata continuation is invalid."
            ) from error

    async def _resolve(self, partition: CollectionPartition) -> CollectionPage:
        state, article = self._state(partition)
        if state["stage"] == "rpc":
            response = await self._http.post_bytes(
                "https://news.google.com/_/DotsSplashUi/data/batchexecute",
                resolution_form(
                    article.identity, state["timestamp"], state["signature"]
                ),
            )
            destination = publisher_destination(response.body, article.source_root)
            return self._lead(article, destination)
        params = {
            "hl": article.locale[0],
            "gl": article.locale[1],
            "ceid": article.locale[2],
        }
        url = (
            state.get("page_url")
            or "https://news.google.com/rss/articles/"
            + article.identity
            + "?"
            + urlencode(params)
        )
        try:
            if google_article_id(url) != article.identity:
                raise ValueError("Mismatched page")
        except (ValueError, TypeError) as error:
            raise CollectionProviderError(
                "invalid_response", "Google metadata continuation URL is invalid."
            ) from error
        response = await self._http.get_bytes(
            url, {}, accepted_statuses=(200, *_REDIRECTS)
        )
        if response.status_code in _REDIRECTS:
            location = urljoin(url, response.redirect_location or "")
            try:
                if not response.redirect_location:
                    raise ValueError("Missing destination")
                if public_document_host(location) != "news.google.com":
                    validate_destination(location, article.source_root)
                    return self._lead(article, location)
                if (
                    google_article_id(location) != article.identity
                    or state["redirects"] >= 3
                ):
                    raise ValueError("Unbounded metadata redirect")
            except ValueError as error:
                raise CollectionProviderError(
                    "invalid_response",
                    "Google publisher destination or redirect is invalid.",
                ) from error
            state.update(page_url=location, redirects=state["redirects"] + 1)
        else:
            timestamp, signature = article_parameters(
                response.body.decode("utf-8", errors="replace"), article.identity
            )
            state.update(
                stage="rpc",
                timestamp=timestamp,
                signature=signature,
                captured=self._clock().isoformat(),
            )
        return CollectionPage(next_cursor=self._cursor(state))

    @staticmethod
    def _lead(article: GoogleArticleMetadata, destination: str) -> CollectionPage:
        return CollectionPage(
            leads=(
                NewsFeedItem(
                    "google-news:" + article.identity,
                    article.publisher,
                    article.title,
                    destination,
                    None,
                    None,
                    indexed_at=article.indexed_at,
                    search_title=article.title,
                ),
            )
        )

    async def aclose(self) -> None:
        await self._http.aclose()
