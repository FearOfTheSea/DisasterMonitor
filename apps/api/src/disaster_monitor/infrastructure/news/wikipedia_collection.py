"""Dated editorial citation leads; publisher documents alone supply event evidence."""

from datetime import date, timedelta

import httpx

from disaster_monitor.domain.collection import (
    CollectionPage,
    CollectionPartition,
    CollectionProviderError,
)
from disaster_monitor.infrastructure.news.collection_http import CollectionHttp
from disaster_monitor.infrastructure.news.wikipedia_citations import (
    MONTHS,
    CitationCapacityError,
    parse_citations,
    parse_earthquake_citations,
    parse_weather_citations,
)


class WikipediaCitationCollectionProvider:
    source_id = "wikipedia-citation-discovery"
    supports_time_filter = False
    supports_alternates = False
    queries = (
        "current-events-citations",
        "weather-timeline-citations",
        "earthquake-timeline-citations",
    )

    endpoint = "https://en.wikipedia.org/w/api.php"

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        minimum_interval: float = 2,
        timeout_seconds: float = 15,
        maximum_citations: int = 1000,
    ) -> None:
        if not 1 <= maximum_citations <= 5000:
            raise ValueError("Citation page bound must be between 1 and 5000.")
        self._maximum_citations = maximum_citations
        self._http = CollectionHttp(
            client=client,
            minimum_interval=minimum_interval,
            timeout_seconds=timeout_seconds,
            user_agent="DisasterMonitorBot/1.0 (https://github.com/FearOfTheSea/DisasterMonitor)",
        )

    async def fetch_page(self, partition: CollectionPartition) -> CollectionPage:
        latest = partition.start.date()
        earliest = latest - timedelta(days=31)
        monthly = partition.query == "current-events-citations"
        periods = (
            _months(latest, earliest)
            if monthly
            else tuple(
                date(year, 1, 1) for year in range(latest.year, earliest.year - 1, -1)
            )
        )
        if partition.query not in self.queries or partition.cursor not in (
            "",
            "1",
            "2",
        ):
            raise CollectionProviderError(
                "invalid_response", "Citation index continuation is invalid."
            )
        index = int(partition.cursor or "0")
        if index >= len(periods):
            raise CollectionProviderError(
                "invalid_response", "Citation index continuation is outside its bound."
            )
        period = periods[index]
        title = (
            f"Portal:Current events/{MONTHS[period.month - 1]} {period.year}"
            if monthly
            else (
                f"List of earthquakes in {period.year}"
                if partition.query == "earthquake-timeline-citations"
                else f"Weather of {period.year}"
            )
        )
        response = await self._http.get_json(
            self.endpoint,
            {
                "action": "parse",
                "page": title,
                "prop": "text|revid",
                "format": "json",
                "formatversion": "2",
                "maxlag": "5",
            },
        )
        payload = response.payload
        if not isinstance(payload, dict):
            raise CollectionProviderError(
                "invalid_response", "Citation index response is invalid."
            )
        error = payload.get("error")
        if isinstance(error, dict):
            busy = error.get("code") in ("maxlag", "ratelimited")
            raise CollectionProviderError(
                "rate_limited" if busy else "invalid_response",
                "Citation index API is busy."
                if busy
                else "Citation index API returned an error.",
                60 if busy else None,
            )
        parsed = payload.get("parse")
        if not isinstance(parsed, dict) or parsed.get("title") != title:
            raise CollectionProviderError(
                "invalid_response", "Citation index page identity is invalid."
            )
        html, revision = parsed.get("text"), parsed.get("revid")
        if not isinstance(html, str) or type(revision) is not int or revision <= 0:
            raise CollectionProviderError(
                "invalid_response", "Citation index content metadata is invalid."
            )
        try:
            if monthly:
                leads, invalid_links = parse_citations(
                    html,
                    month=period,
                    earliest=earliest,
                    latest=latest,
                    revision=revision,
                    maximum_citations=self._maximum_citations,
                )
            else:
                parser = (
                    parse_earthquake_citations
                    if partition.query == "earthquake-timeline-citations"
                    else parse_weather_citations
                )
                leads, invalid_links = parser(
                    html,
                    year=period.year,
                    earliest=earliest,
                    latest=latest,
                    revision=revision,
                    maximum_citations=self._maximum_citations,
                )
        except CitationCapacityError as error:
            raise CollectionProviderError("capacity_exhausted", str(error)) from error
        except ValueError as error:
            raise CollectionProviderError("invalid_response", str(error)) from error
        return CollectionPage(
            leads=leads,
            next_cursor=str(index + 1) if index + 1 < len(periods) else None,
            saturated=True,
            notices=(
                f"Wikipedia editorial citation index: {title}, revision {revision}.",
                "English disaster-category, annual weather and earthquake citations "
                "are editorial leads, "
                "not exhaustive news coverage. Index summaries and calendar dates "
                "do not establish publisher claims, publication or event onset. "
                "Only retrieved publisher evidence can enter the reporting window.",
                *(
                    (
                        f"Citation index excluded {invalid_links} non-article, "
                        "unsafe, unresolved or internal citation links.",
                    )
                    if invalid_links
                    else ()
                ),
            ),
        )

    async def aclose(self) -> None:
        await self._http.aclose()


def _months(latest: date, earliest: date) -> tuple[date, ...]:
    result = []
    month = latest.replace(day=1)
    oldest = earliest.replace(day=1)
    while month >= oldest:
        result.append(month)
        month = (month - timedelta(days=1)).replace(day=1)
    return tuple(result)
