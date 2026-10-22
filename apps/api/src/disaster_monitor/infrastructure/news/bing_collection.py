"""Public news RSS leads; publisher retrieval alone can establish report evidence."""

from datetime import UTC
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

import httpx
from defusedxml import ElementTree

from disaster_monitor.domain.collection import (
    CollectionPage,
    CollectionPartition,
    CollectionProviderError,
)
from disaster_monitor.domain.news import NewsFeedItem
from disaster_monitor.infrastructure.news.collection_http import CollectionHttp
from disaster_monitor.infrastructure.news.public_documents import public_document_host

# Keep provider query syntax here rather than sharing GDELT's Boolean grammar.
# Public RSS diagnostics returned unrelated headlines for grouped alternatives.
# A mandatory phrase is still only a search hint, never event evidence.
_QUERY_GROUPS = (
    (("earthquake",), "killed", ("terremoto",), ("séisme",)),
    (("flood", "mine flood"), "killed", ("inundaciones",), ("inondations",)),
    (
        ("wildfire", "veld fire"),
        "killed",
        ("incendio forestal", "incendios forestales"),
        ("incendie de forêt",),
    ),
    (
        ("landslide", "mudslide", "rockfall"),
        "killed",
        ("deslizamiento de tierra",),
        ("glissement de terrain",),
    ),
    (("drought",), "deaths", ("sequía",), ("sécheresse",)),
    (
        ("hurricane", "typhoon", "cyclone"),
        "killed",
        ("huracán", "tifón", "ciclón"),
        ("ouragan", "typhon", "cyclone"),
    ),
    (
        ("volcanic eruption", "volcano erupts"),
        "deaths",
        ("erupción volcánica",),
        ("éruption volcanique",),
    ),
)


class _HintText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self.hidden += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def _summary_hint(description: str) -> str | None:
    parser = _HintText()
    parser.feed(description[:10_000])
    return " ".join(" ".join(parser.parts).split())[:1500] or None


class BingRssCollectionProvider:
    source_id = "bing-rss-discovery"
    supports_alternates = True
    supports_time_filter = False
    queries = tuple(
        query
        for english, fatality, spanish, french in _QUERY_GROUPS
        for query in (
            *(f'"{hazard}"' for hazard in english),
            *(f'"{hazard}" {fatality}' for hazard in english),
            *(
                f'"{hazard}" {death_word}'
                for hazard in spanish
                for death_word in ("muertos", "fallecidos")
            ),
            *(f'"{hazard}" morts' for hazard in french),
        )
    ) + (
        '"gempa" meninggal',
        '"banjir" tewas',
        '"longsor" tewas',
        '"deslizamento" mortos',
        '"deslizamento" morreu',
        '"enchente" mortos',
        '"enxurrada" morreu',
    )
    endpoint = "https://www.bing.com/news/search"

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 15,
        minimum_interval: float = 2,
    ) -> None:
        self._http = CollectionHttp(
            client=client,
            timeout_seconds=timeout_seconds,
            minimum_interval=minimum_interval,
        )

    async def fetch_page(self, partition: CollectionPartition) -> CollectionPage:
        if partition.cursor not in ("", "relevance"):
            raise CollectionProviderError(
                "invalid_response", "News RSS continuation is invalid."
            )
        recent = not partition.cursor
        response = await self._http.get_bytes(
            self.endpoint,
            {
                "q": partition.query,
                "format": "rss",
                "mkt": "en-US",
                "qft": 'interval="9" sortbydate="1"' if recent else 'interval="9"',
            },
        )
        try:
            root = ElementTree.fromstring(response.body)
            if _name(root.tag) != "rss" or root.find("channel") is None:
                raise ValueError("Not an RSS channel")
        except Exception as error:
            raise CollectionProviderError(
                "invalid_response", "News service returned invalid or unsafe RSS."
            ) from error
        leads: dict[str, NewsFeedItem] = {}
        invalid = 0
        for element in root.iter():
            if _name(element.tag) != "item":
                continue
            fields = {_name(c.tag): (c.text or "").strip() for c in element}
            item = _lead(fields)
            if item is None:
                invalid += 1
            else:
                leads[item.canonical_url] = item
        return CollectionPage(
            leads=tuple(leads.values()),
            next_cursor="relevance" if recent else None,
            saturated=True,
            notices=(
                "Public RSS ordering: " + ("most recent." if recent else "best match."),
                "Public news RSS provides bounded recent headlines, without "
                "historical date filtering or a complete pagination contract. "
                "Each query checks at most these two orderings. "
                "Publisher publication metadata determines reporting-window "
                "eligibility.",
                *(
                    (f"News RSS excluded {invalid} malformed leads.",)
                    if invalid
                    else ()
                ),
            ),
        )

    async def aclose(self) -> None:
        await self._http.aclose()


def _name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold()


def _lead(fields: dict[str, str]) -> NewsFeedItem | None:
    url = fields.get("link", "")
    try:
        parsed = urlsplit(url)
        if parsed.hostname in {"www.bing.com", "bing.com"}:
            values = parse_qs(parsed.query).get("url", [])
            if len(values) != 1:
                return None
            url = values[0]
            parsed = urlsplit(url)
        hostname = public_document_host(url)
        if (
            hostname is None
            or hostname in {"www.bing.com", "bing.com"}
            or not fields.get("title")
        ):
            return None
        indexed = parsedate_to_datetime(fields.get("pubdate", ""))
        if indexed.tzinfo is None:
            return None
    except (ValueError, TypeError):
        return None
    return NewsFeedItem(
        external_id=url,
        publisher=fields.get("source") or hostname,
        title=fields["title"],
        canonical_url=url,
        published_at=None,
        updated_at=None,
        indexed_at=indexed.astimezone(UTC),
        discovery_hint=_summary_hint(fields.get("description", "")),
    )
