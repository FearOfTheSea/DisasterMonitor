"""Quarter-hour GKG themes select publisher leads, never establish event facts."""

import html
import io
import ipaddress
import re
import zipfile
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import httpx

from disaster_monitor.domain.collection import (
    CollectionPage,
    CollectionPartition,
    CollectionProviderError,
)
from disaster_monitor.domain.news import NewsFeedItem
from disaster_monitor.infrastructure.news.collection_http import CollectionHttp
from disaster_monitor.infrastructure.news.public_documents import public_document_host

_THEMES = {
    "earthquake": ("EARTHQUAKE", "EARTHQUAKES"),
    "flood": ("FLOOD", "FLOODS", "FLOODING", "FLOODED"),
    "wildfire": ("WILDFIRE", "WILDFIRES", "FOREST_FIRE", "FOREST_FIRES"),
    "landslide": ("LANDSLIDE", "LANDSLIDES", "MUDSLIDE", "MUDSLIDES"),
    "tropical cyclone": (
        "CYCLONE",
        "CYCLONES",
        "HURRICANE",
        "HURRICANES",
        "TYPHOON",
        "TYPHOONS",
    ),
    "volcanic eruption": ("VOLCANO", "VOLCANOES", "VOLCANIC", "ERUPTION", "ERUPTIONS"),
    "drought": ("DROUGHT", "DROUGHTS"),
}
_HAZARD_THEMES = {
    "NATURAL_DISASTER_" + theme: hazard
    for hazard, themes in _THEMES.items()
    for theme in themes
}
_TITLE = re.compile(r"<PAGE_TITLE>([^\r\n]{1,12000}?)</PAGE_TITLE>")
_NOTICE = (
    "GDELT GKG archive: body-derived themes and native titles select leads only. "
    "Index metadata never establishes publisher publication, onset, casualties, "
    "location or photographs. Publisher retrieval determines eligibility. "
    "Continuation checks both language streams at quarter-hour resolution. "
    "The newest fifteen minutes, missing files and unrecognized themes remain "
    "coverage gaps; cold historical scans require thousands of archive requests."
)


class GdeltGkgCollectionProvider:
    source_id = "gdelt-gkg-discovery"
    supports_alternates = False
    supports_time_filter = True
    queries = ("english-body-themes", "translated-body-themes")
    endpoint = "https://data.gdeltproject.org/gdeltv2/"

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 30,
        minimum_interval: float = 1,
        maximum_decoded_bytes: int = 128_000_000,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not 1000 <= maximum_decoded_bytes <= 128_000_000:
            raise ValueError("GKG decoded limit must be between1000 and128000000.")
        self._maximum_decoded_bytes = maximum_decoded_bytes
        self._clock = clock or (lambda: datetime.now(UTC))
        self._http = CollectionHttp(
            client=client,
            timeout_seconds=timeout_seconds,
            minimum_interval=minimum_interval,
            maximum_bytes=16_000_000,
        )

    async def fetch_page(self, partition: CollectionPartition) -> CollectionPage:
        stamps, index = self._position(partition)
        if not stamps:
            return CollectionPage(saturated=True, notices=(_NOTICE,))
        stamp = stamps[index]
        name = stamp.strftime("%Y%m%d%H%M%S")
        suffix = (
            ".translation.gkg.csv" if partition.query == self.queries[1] else ".gkg.csv"
        )
        member = name + suffix
        url = self.endpoint + member + ".zip"
        response = await self._http.get_bytes(url, {}, accepted_statuses=(200, 404))
        notices = [_NOTICE]
        leads: tuple[NewsFeedItem, ...] = ()
        if response.status_code == 404:
            notices.append(
                "GDELT GKG HTTP404: a requested archive file was unavailable. "
                "Journal request bounds retain this gap; "
                "it is not absence of reporting."
            )
        else:
            leads, invalid = self._leads(response.body, stamp, member, url)
            if invalid:
                notices.append(f"GDELT GKG excluded {invalid} unusable metadata rows.")
        return CollectionPage(
            leads=leads,
            next_cursor=f"{stamps[0].strftime('%Y%m%d%H%M%S')}:{index + 1}"
            if index + 1 < len(stamps)
            else None,
            saturated=True,
            notices=tuple(notices),
            requested_start=stamp,
            requested_end=stamp + timedelta(minutes=15),
        )

    def _position(
        self, partition: CollectionPartition
    ) -> tuple[tuple[datetime, ...], int]:
        def invalid() -> CollectionProviderError:
            return CollectionProviderError(
                "invalid_response", "GKG continuation is invalid."
            )

        if (
            partition.query not in self.queries
            or partition.alternate_for
            or partition.end - partition.start > timedelta(days=32)
        ):
            raise invalid()
        step = timedelta(minutes=15)
        lower = _quarter_hour(partition.start)
        if lower < partition.start:
            lower += step
        safe = self._clock().astimezone(UTC) - timedelta(minutes=15)
        upper = _quarter_hour(min(partition.end - timedelta(microseconds=1), safe))
        index = 0
        if partition.cursor:
            if not re.fullmatch(r"\d{14}:\d{1,5}", partition.cursor):
                raise invalid()
            text, offset = partition.cursor.split(":")
            try:
                frozen = datetime.strptime(text, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
            except ValueError as error:
                raise invalid() from error
            if _quarter_hour(frozen) != frozen or not lower <= frozen <= upper:
                raise invalid()
            upper, index = frozen, int(offset)
        count = (upper - lower) // step + 1
        if count <= 0 and not partition.cursor:
            return (), 0
        if not 0 <= index < count:
            raise invalid()
        return tuple(upper - i * step for i in range(count)), index

    def _leads(
        self, body: bytes, stamp: datetime, member: str, url: str
    ) -> tuple[tuple[NewsFeedItem, ...], int]:
        leads: dict[str, NewsFeedItem] = {}
        invalid = 0
        try:
            with zipfile.ZipFile(io.BytesIO(body)) as archive:
                infos = archive.infolist()
                if (
                    len(infos) != 1
                    or infos[0].filename != member
                    or infos[0].flag_bits & 1
                    or not 0 < infos[0].file_size <= self._maximum_decoded_bytes
                ):
                    raise ValueError("Unbounded or unexpected archive member")
                decoded = 0
                rows = 0
                valid_rows = 0
                with archive.open(infos[0]) as stream:
                    while line := stream.readline(1_000_001):
                        decoded += len(line)
                        rows += 1
                        if (
                            len(line) > 1_000_000
                            or decoded > self._maximum_decoded_bytes
                            or rows > 25_000
                        ):
                            raise ValueError("Archive row or decoded bound exceeded")
                        try:
                            fields = line.decode("utf8").rstrip("\r\n").split("\t")
                        except UnicodeError:
                            invalid += 1
                            continue
                        if len(fields) != 27:
                            invalid += 1
                            continue
                        valid_rows += 1
                        lead = _lead(fields, stamp, url)
                        if lead:
                            leads.setdefault(lead.canonical_url, lead)
                        elif (
                            fields[2] == "1"
                            and set(fields[7].split(";")) & _HAZARD_THEMES.keys()
                        ):
                            invalid += 1
                if not valid_rows:
                    raise ValueError("Archive has no valid UTF8 schema rows")
        except (
            ValueError,
            UnicodeError,
            OSError,
            EOFError,
            zipfile.BadZipFile,
            RuntimeError,
            NotImplementedError,
        ) as error:
            raise CollectionProviderError(
                "invalid_response",
                "GDELT GKG archive is malformed or exceeds its bounds.",
            ) from error
        return tuple(leads.values()), invalid

    async def aclose(self) -> None:
        await self._http.aclose()


def _quarter_hour(value: datetime) -> datetime:
    value = value.astimezone(UTC).replace(second=0, microsecond=0)
    return value - timedelta(minutes=value.minute % 15)


def _lead(fields: list[str], stamp: datetime, archive_url: str) -> NewsFeedItem | None:
    themes = set(fields[7].split(";"))
    hazards = sorted({_HAZARD_THEMES[t] for t in themes & _HAZARD_THEMES.keys()})
    title_match = _TITLE.search(fields[26])
    title = " ".join(html.unescape(title_match[1]).split()) if title_match else ""
    url = fields[4]
    host = public_document_host(url)
    name = stamp.strftime("%Y%m%d%H%M%S")
    if (
        fields[2] != "1"
        or not hazards
        or not 0 < len(title) <= 2000
        or not host
        or len(url) > 4096
        or fields[1] != name
        or not re.fullmatch(name + r"-T?\d{1,12}", fields[0])
    ):
        return None
    try:
        if not ipaddress.ip_address(host).is_global:
            return None
    except ValueError:
        pass
    hints = " ".join(hazards)
    if themes & {"KILL", "CRISISLEX_T03_DEAD"}:
        hints += "; death-related index theme (unverified)"
    return NewsFeedItem(
        external_id=f"{archive_url}#{fields[0]}",
        publisher=host,
        title=title,
        canonical_url=url,
        published_at=None,
        updated_at=None,
        indexed_at=stamp,
        discovery_hint=hints,
        search_title=title[:300],
    )
