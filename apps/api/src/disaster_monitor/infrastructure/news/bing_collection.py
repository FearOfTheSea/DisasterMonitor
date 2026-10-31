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
_REGIONAL_QUERY_MARKETS = {
    '"gempa" meninggal': "id-ID",
    '"banjir" tewas': "id-ID",
    '"longsor" tewas': "id-ID",
    '"kebakaran hutan" tewas': "id-ID",
    '"karhutla" meninggal': "id-ID",
    '"kekeringan" meninggal': "id-ID",
    '"siklon tropis" tewas': "id-ID",
    '"topan" tewas': "id-ID",
    '"erupsi gunung" tewas': "id-ID",
    '"letusan gunung" meninggal': "id-ID",
    '"deslizamento" mortos': "pt-BR",
    '"deslizamento" morreu': "pt-BR",
    '"enchente" mortos': "pt-BR",
    '"enxurrada" morreu': "pt-BR",
}
_ADDITIONAL_QUERY_MARKETS = {
    f'"{hazard}" {death_word}': market
    for market, hazards, death_words in (
        (
            "de-DE",
            (
                "Erdbeben",
                "Hochwasser",
                "Waldbrand",
                "Erdrutsch",
                "Wirbelsturm",
                "Vulkanausbruch",
                "Dürre",
            ),
            ("Tote", "starben"),
        ),
        (
            "tr-TR",
            (
                "deprem",
                "sel",
                "orman yangını",
                "heyelan",
                "kasırga",
                "volkanik patlama",
                "kuraklık",
            ),
            ("öldü", '"hayatını kaybetti"'),
        ),
        (
            "ar-SA",
            (
                "زلزال",
                "فيضانات",
                "حرائق الغابات",
                "انهيار أرضي",
                "إعصار",
                "ثوران بركاني",
                "جفاف",
            ),
            ("قتلى", "وفيات"),
        ),
    )
    for hazard in hazards
    for death_word in death_words
}
_NATIVE_QUERY_MARKETS = {
    **{
        f'"{hazard}" {death_word}': "es-MX"
        for _, _, spanish, _ in _QUERY_GROUPS
        for hazard in spanish
        for death_word in ("muertos", "fallecidos")
    },
    **{
        f'"{hazard}" morts': "fr-FR"
        for _, _, _, french in _QUERY_GROUPS
        for hazard in french
    },
    **_REGIONAL_QUERY_MARKETS,
    **_ADDITIONAL_QUERY_MARKETS,
}


def _request_page(partition: CollectionPartition) -> tuple[str, bool, str | None]:
    """Reach configured markets first; preserve already issued cursor meanings."""
    native_market = (
        _NATIVE_QUERY_MARKETS.get(partition.query)
        if partition.alternate_for is None
        else None
    )
    if not partition.cursor:
        if native_market:
            return native_market, True, "native-first-relevance"
        return "en-US", True, "relevance"
    if native_market:
        if partition.cursor == "native-first-relevance":
            return native_market, False, "us-recent"
        if partition.cursor == "us-recent":
            return "en-US", True, "us-relevance"
        if partition.cursor == "us-relevance":
            return "en-US", False, None
    # Stored U.S.-first chains must finish without replaying earlier requests.
    if partition.cursor == "relevance":
        return "en-US", False, "native-recent" if native_market else None
    if native_market:
        if partition.cursor == "native-recent":
            return native_market, True, "native-relevance"
        if partition.cursor == "native-relevance":
            return native_market, False, None
    raise CollectionProviderError(
        "invalid_response", "News RSS continuation is invalid."
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
    queries = (
        tuple(
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
        )
        + tuple(_REGIONAL_QUERY_MARKETS)
        + tuple(_ADDITIONAL_QUERY_MARKETS)
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
        market, recent, next_cursor = _request_page(partition)
        response = await self._http.get_bytes(
            self.endpoint,
            {
                "q": partition.query,
                "format": "rss",
                "mkt": market,
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
            next_cursor=next_cursor,
            saturated=True,
            notices=(
                "Public RSS ordering: " + ("most recent." if recent else "best match."),
                f"Public RSS market: {market}.",
                "Public news RSS provides bounded recent headlines, without "
                "historical date filtering or a complete pagination contract. "
                "Each query checks at most two orderings per market. "
                "Configured native-language seeds start in their native market "
                "and retain U.S. fallback orderings; "
                "other queries check the U.S. market only. "
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
