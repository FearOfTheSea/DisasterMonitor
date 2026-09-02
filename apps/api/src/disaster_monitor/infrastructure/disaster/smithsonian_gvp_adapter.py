"""Bounded Smithsonian/USGS volcanic-eruption event discovery."""

from datetime import UTC, date, datetime, timedelta

import httpx

from disaster_monitor.application.disaster import (
    DisasterQuery,
    ProviderBatch,
    ProviderIssue,
    WorldwideDisasterEvent,
    WorldwideDisasterQuery,
)
from disaster_monitor.application.ports.geography import CountryCatalog
from disaster_monitor.domain.disaster import (
    Country,
    Disaster,
    DisasterEvent,
    EventGeographyStatus,
    SourceAuthority,
    SourceReference,
    point_event_geometry,
)
from disaster_monitor.infrastructure.disaster.errors import (
    DisasterProviderError,
    DisasterProviderResponseError,
)
from disaster_monitor.infrastructure.disaster.http import (
    SourcePayloadRecorder,
    build_snapshot_capture,
    get_json,
    get_text,
)
from disaster_monitor.infrastructure.disaster.smithsonian_gvp_parsing import (
    _feature_collection,
    _GvpEruption,
    _GvpVolcano,
    _parse_eruption_feature,
    _parse_volcano_feature,
    _parse_wvar_rss,
    _precise_wvar_date,
    _source_report_url,
    _week_starts,
    _wfs_params,
    _WvarFeedEntry,
    _WvarRow,
    _WvarSummaryParser,
)

WVAR_URL = "https://volcano.si.edu/reports_weekly.cfm"
WVAR_RSS_URL = "https://volcano.si.edu/news/WeeklyVolcanoRSS.xml"
GVP_WFS_URL = "https://webservices.volcano.si.edu/geoserver/GVP-VOTW/ows"
_MAX_SEARCH_DAYS = 30
_MAX_FEATURES = 100
_MAX_ERUPTION_FEATURES = 2_000
_ADMITTED_REPORT_TYPES = frozenset(
    {"New Eruptive Activity", "Continuing Eruptive Activity"}
)


class SmithsonianGvpAdapter:
    """Discover explicit WVAR eruptive-activity candidates with GVP metadata."""

    provider_name = "Smithsonian / USGS Weekly Volcanic Activity Report"
    source_id = "smithsonian-usgs-volcanic-activity"
    allowed_hosts = frozenset({"volcano.si.edu", "webservices.volcano.si.edu"})

    def __init__(
        self,
        *,
        geography: CountryCatalog,
        client: httpx.AsyncClient | None = None,
        snapshot_recorder: SourcePayloadRecorder | None = None,
        timeout_seconds: float = 10.0,
        max_response_bytes: int = 1_000_000,
    ) -> None:
        self._geography = geography
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = client is None
        self._snapshot_recorder = snapshot_recorder
        self._max_response_bytes = max_response_bytes

    def _interval(
        self, query: DisasterQuery | WorldwideDisasterQuery, now: datetime
    ) -> tuple[datetime, datetime]:
        requested_days = min(
            _MAX_SEARCH_DAYS,
            max(0, query.time_window_days),
        )
        start = getattr(query, "date_from", None) or now - timedelta(
            days=requested_days
        )
        end = getattr(query, "date_to", None) or now
        if end - start > timedelta(days=_MAX_SEARCH_DAYS):
            start = end - timedelta(days=_MAX_SEARCH_DAYS)
        return start, end

    async def _wvar_page(
        self, week_start: date, now: datetime
    ) -> tuple[tuple[_WvarRow, ...], str | None]:
        weekstart = week_start.strftime("%Y%m%d")
        capture = build_snapshot_capture(
            self._snapshot_recorder,
            source_id=self.source_id,
            parameters={"weekstart": weekstart},
            rights_id="smithsonian-gvp-wvar-terms-2026-08",
            retrieved_at=now,
        )
        html = await get_text(
            self._client,
            WVAR_URL,
            params={"weekstart": weekstart},
            allowed_hosts=self.allowed_hosts,
            max_bytes=self._max_response_bytes,
            provider_name=self.provider_name,
            capture=capture,
        )
        parser = _WvarSummaryParser()
        parser.feed(html)
        parser.close()
        rows = parser.rows()
        if not rows:
            raise DisasterProviderResponseError(
                "The WVAR response did not contain its summary table.",
                reason_code="malformed_response",
            )
        return (
            rows,
            capture.snapshot.snapshot_id if capture and capture.snapshot else None,
        )

    async def _wvar_feed(
        self, now: datetime
    ) -> tuple[tuple[_WvarFeedEntry, ...], tuple[ProviderIssue, ...], str | None]:
        capture = build_snapshot_capture(
            self._snapshot_recorder,
            source_id=self.source_id,
            parameters={"format": "rss", "scope": "current_week"},
            rights_id="smithsonian-gvp-wvar-terms-2026-08",
            retrieved_at=now,
        )
        xml = await get_text(
            self._client,
            WVAR_RSS_URL,
            allowed_hosts=self.allowed_hosts,
            max_bytes=self._max_response_bytes,
            provider_name=self.provider_name,
            capture=capture,
        )
        entries, issues = _parse_wvar_rss(xml, self.provider_name)
        return (
            entries,
            issues,
            capture.snapshot.snapshot_id if capture and capture.snapshot else None,
        )

    async def _gvp_volcanoes(
        self, numbers: tuple[int, ...], now: datetime
    ) -> tuple[dict[int, _GvpVolcano], list[ProviderIssue]]:
        if not numbers:
            return {}, []
        params = _wfs_params(
            "GVP-VOTW:Smithsonian_VOTW_Holocene_Volcanoes",
            (
                "Volcano_Number",
                "Volcano_Name",
                "Country",
                "Region",
                "Latitude",
                "Longitude",
            ),
            numbers,
        )
        capture = build_snapshot_capture(
            self._snapshot_recorder,
            source_id=self.source_id,
            parameters={
                "layer": "volcanoes",
                "volcano_numbers": ",".join(map(str, numbers)),
            },
            rights_id="smithsonian-gvp-votw-terms-2026-08",
            retrieved_at=now,
        )
        payload = await get_json(
            self._client,
            GVP_WFS_URL,
            params=params,
            allowed_hosts=self.allowed_hosts,
            max_bytes=self._max_response_bytes,
            provider_name=self.provider_name,
            capture=capture,
        )
        parsed: dict[int, _GvpVolcano] = {}
        issues: list[ProviderIssue] = []
        for index, raw in enumerate(_feature_collection(payload, "volcano")):
            feature, issue = _parse_volcano_feature(raw, index)
            if feature is not None and feature.number not in parsed:
                parsed[feature.number] = feature
            if issue is not None:
                issues.append(issue)
        return parsed, issues

    async def _gvp_eruptions(
        self, numbers: tuple[int, ...], now: datetime
    ) -> tuple[tuple[_GvpEruption, ...], list[ProviderIssue]]:
        if not numbers:
            return (), []
        params = _wfs_params(
            "GVP-VOTW:Smithsonian_VOTW_Holocene_Eruptions",
            (
                "Volcano_Number",
                "Eruption_Number",
                "StartDateYearModifier",
                "StartDateYear",
                "StartDateYearUncertainty",
                "StartDateDayModifier",
                "StartDateMonth",
                "StartDateDay",
                "StartDateDayUncertainty",
            ),
            numbers,
            count=_MAX_ERUPTION_FEATURES,
        )
        capture = build_snapshot_capture(
            self._snapshot_recorder,
            source_id=self.source_id,
            parameters={
                "layer": "eruptions",
                "volcano_numbers": ",".join(map(str, numbers)),
            },
            rights_id="smithsonian-gvp-votw-terms-2026-08",
            retrieved_at=now,
        )
        payload = await get_json(
            self._client,
            GVP_WFS_URL,
            params=params,
            allowed_hosts=self.allowed_hosts,
            max_bytes=self._max_response_bytes,
            provider_name=self.provider_name,
            capture=capture,
        )
        records: list[_GvpEruption] = []
        issues: list[ProviderIssue] = []
        for index, raw in enumerate(_feature_collection(payload, "eruption")):
            record, issue = _parse_eruption_feature(raw, index)
            if record is not None:
                records.append(record)
            if issue is not None:
                issues.append(issue)
        return tuple(records), issues

    def _resolve_time(
        self,
        row: _WvarRow,
        week_start: date,
        eruptions: tuple[_GvpEruption, ...],
    ) -> tuple[date, str | None] | None:
        wvar_start = _precise_wvar_date(row.start_text)
        candidates = tuple(
            item for item in eruptions if item.volcano_number == row.volcano_number
        )
        if wvar_start is not None:
            matched = next(
                (item for item in candidates if item.start == wvar_start), None
            )
            return (
                wvar_start,
                f"gvp-eruption:{matched.eruption_number}" if matched else None,
            )
        in_week = tuple(
            item
            for item in candidates
            if week_start - timedelta(days=30)
            <= item.start
            <= week_start + timedelta(days=6)
        )
        if len(in_week) == 1:
            return in_week[0].start, f"gvp-eruption:{in_week[0].eruption_number}"
        if row.report_type == "Continuing Eruptive Activity":
            eligible = tuple(
                item
                for item in candidates
                if item.start <= week_start + timedelta(days=6)
            )
            if eligible:
                latest_start = max(item.start for item in eligible)
                latest = tuple(item for item in eligible if item.start == latest_start)
                if len(latest) == 1:
                    return (
                        latest[0].start,
                        f"gvp-eruption:{latest[0].eruption_number}",
                    )
        return None

    def _source(
        self,
        row: _WvarRow,
        week_start: date,
        now: datetime,
        snapshot_id: str | None,
        published_at: datetime | None,
    ) -> SourceReference:
        weekstart = week_start.strftime("%Y%m%d")
        return SourceReference(
            source_id=self.source_id,
            publisher=(
                "Smithsonian Global Volcanism Program / USGS Volcano Hazards Program"
            ),
            title="Smithsonian / USGS Weekly Volcanic Activity Report",
            canonical_url=(
                _source_report_url(row.report_url)
                or f"{WVAR_URL}?weekstart={weekstart}"
            ),
            published_at=published_at,
            updated_at=None,
            retrieved_at=now,
            authority=SourceAuthority.SCIENTIFIC_AUTHORITY,
            snapshot_id=snapshot_id,
        )

    def _affiliated_codes(self, volcano: _GvpVolcano) -> frozenset[str]:
        return frozenset(
            country.alpha3_code
            for label in volcano.countries
            for country in self._geography.find_mentions(label)
        )

    def _candidate(
        self,
        row: _WvarRow,
        volcano: _GvpVolcano,
        eruption: tuple[date, str | None],
        *,
        week_start: date,
        snapshot_id: str | None,
        published_at: datetime | None,
        country: Country | None,
        now: datetime,
    ) -> DisasterEvent | WorldwideDisasterEvent | None:
        event_date, eruption_id = eruption
        source = self._source(row, week_start, now, snapshot_id, published_at)
        provider_ids = [f"gvp-volcano:{volcano.number}"]
        if eruption_id is not None:
            provider_ids.append(eruption_id)
        if row.report_id:
            provider_ids.append(f"wvar:{row.report_id}")
        location = volcano.name + (f", {volcano.region}" if volcano.region else "")
        geometry = point_event_geometry(volcano.latitude, volcano.longitude, source)
        if country is None:
            return WorldwideDisasterEvent(
                event_id=eruption_id
                or f"gvp-eruption:{volcano.number}:{event_date:%Y%m%d}",
                disaster=Disaster.VOLCANIC_ERUPTION,
                location=location,
                event_time=datetime(
                    event_date.year, event_date.month, event_date.day, tzinfo=UTC
                ),
                source=source,
                geometry=geometry,
                provider_ids=tuple(provider_ids),
            )
        geography_status = EventGeographyStatus.IN_COUNTRY
        if not self._geography.contains(country, volcano.latitude, volcano.longitude):
            if country.alpha3_code not in self._affiliated_codes(volcano):
                return None
            geography_status = EventGeographyStatus.COUNTRY_ASSOCIATED_OFFSHORE
        return DisasterEvent(
            event_id=eruption_id
            or f"gvp-eruption:{volcano.number}:{event_date:%Y%m%d}",
            disaster=Disaster.VOLCANIC_ERUPTION,
            location=location,
            country=country,
            event_time=datetime(
                event_date.year, event_date.month, event_date.day, tzinfo=UTC
            ),
            source=source,
            geometry=geometry,
            provider_ids=tuple(provider_ids),
            geography_status=geography_status,
        )

    async def _discover(
        self,
        query: DisasterQuery | WorldwideDisasterQuery,
        *,
        now: datetime,
        country: Country | None,
    ) -> ProviderBatch[DisasterEvent | WorldwideDisasterEvent]:
        start, end = self._interval(query, now)
        if end < start:
            return ProviderBatch(
                issues=(
                    ProviderIssue(
                        self.provider_name,
                        "The volcanic-eruption time interval is invalid.",
                        reason_code="invalid_query",
                    ),
                )
            )
        rows: list[tuple[_WvarRow, date, str | None, datetime | None]] = []
        issues: list[ProviderIssue] = []
        discovered_rows: list[tuple[_WvarRow, date, str | None, datetime | None]] = []
        if end >= now - timedelta(days=7):
            try:
                feed_entries, feed_issues, snapshot_id = await self._wvar_feed(now)
            except DisasterProviderError:
                for week_start in _week_starts(start, end):
                    page_rows, snapshot_id = await self._wvar_page(week_start, now)
                    discovered_rows.extend(
                        (row, week_start, snapshot_id, None) for row in page_rows
                    )
            else:
                issues.extend(feed_issues)
                discovered_rows.extend(
                    (
                        entry.row,
                        entry.week_start,
                        snapshot_id,
                        entry.published_at,
                    )
                    for entry in feed_entries
                    if entry.week_start <= end.date()
                    and entry.week_start + timedelta(days=6) >= start.date()
                )
        else:
            for week_start in _week_starts(start, end):
                page_rows, snapshot_id = await self._wvar_page(week_start, now)
                discovered_rows.extend(
                    (row, week_start, snapshot_id, None) for row in page_rows
                )
        for row, week_start, snapshot_id, published_at in discovered_rows:
            report_type = " ".join(row.report_type.split())
            if report_type not in _ADMITTED_REPORT_TYPES:
                if report_type in {
                    "New Unrest",
                    "Continuing Unrest",
                    "Other Observations",
                }:
                    continue
                issues.append(
                    ProviderIssue(
                        self.provider_name,
                        (
                            f"WVAR report type {report_type or '<missing>'!r} was "
                            "not admitted as an eruption."
                        ),
                        reason_code="unsupported_report_type",
                    )
                )
                continue
            if row.volcano_number is None or not row.name or not row.country:
                issues.append(
                    ProviderIssue(
                        self.provider_name,
                        "A malformed WVAR candidate was skipped.",
                        reason_code="invalid_record",
                    )
                )
                continue
            if country is not None:
                row_countries = self._geography.find_mentions(row.country)
                if not row_countries:
                    issues.append(
                        ProviderIssue(
                            self.provider_name,
                            "A WVAR country label could not be resolved.",
                            reason_code="country_identity_unavailable",
                        )
                    )
                    continue
                if all(
                    item.alpha3_code != country.alpha3_code for item in row_countries
                ):
                    continue
            if published_at is not None and published_at > now + timedelta(minutes=5):
                issues.append(
                    ProviderIssue(
                        self.provider_name,
                        "A future-dated WVAR report was skipped.",
                        reason_code="future_source_timestamp",
                    )
                )
                continue
            rows.append((row, week_start, snapshot_id, published_at))
        if not rows:
            if not issues:
                issues.append(
                    ProviderIssue(
                        self.provider_name,
                        "WVAR returned no admitted eruptive activity.",
                        reason_code="empty_result",
                    )
                )
            return ProviderBatch(issues=tuple(issues))
        numbers = tuple(
            sorted(
                {
                    row.volcano_number
                    for row, _, _, _ in rows
                    if row.volcano_number is not None
                }
            )
        )[:_MAX_FEATURES]
        volcanoes, volcano_issues = await self._gvp_volcanoes(numbers, now)
        issues.extend(volcano_issues)
        needs_eruptions = bool(rows)
        eruptions, eruption_issues = (
            await self._gvp_eruptions(numbers, now) if needs_eruptions else ((), [])
        )
        issues.extend(eruption_issues)
        records: dict[str, DisasterEvent | WorldwideDisasterEvent] = {}
        duplicate_ids: set[str] = set()
        for row, week_start, snapshot_id, published_at in rows:
            if row.volcano_number is None:
                continue
            volcano = volcanoes.get(row.volcano_number)
            if volcano is None:
                issues.append(
                    ProviderIssue(
                        self.provider_name,
                        "A WVAR volcano had no matched GVP identity or geography.",
                        reason_code="gvp_identity_unavailable",
                    )
                )
                continue
            resolved = self._resolve_time(row, week_start, eruptions)
            if resolved is None:
                issues.append(
                    ProviderIssue(
                        self.provider_name,
                        "A volcanic candidate had no day-precise eruption start.",
                        reason_code="event_time_precision_unavailable",
                    )
                )
                continue
            record = self._candidate(
                row,
                volcano,
                resolved,
                week_start=week_start,
                snapshot_id=snapshot_id,
                published_at=published_at,
                country=country,
                now=now,
            )
            if record is None:
                issues.append(
                    ProviderIssue(
                        self.provider_name,
                        "A GVP point and affiliation failed country validation.",
                        reason_code="country_mismatch",
                    )
                )
                continue
            if record.event_id in duplicate_ids:
                continue
            existing = records.get(record.event_id)
            if existing is None:
                records[record.event_id] = record
            elif not _equivalent_duplicate(existing, record):
                del records[record.event_id]
                duplicate_ids.add(record.event_id)
                issues.append(
                    ProviderIssue(
                        self.provider_name,
                        "Conflicting duplicate WVAR event identities were excluded.",
                        reason_code="duplicate_identity",
                        detail=f"normalized event {record.event_id!r}",
                    )
                )
        if not records and not issues:
            issues.append(
                ProviderIssue(
                    self.provider_name,
                    "No valid volcanic-eruption records were found.",
                    reason_code="empty_result",
                )
            )
        return ProviderBatch[DisasterEvent | WorldwideDisasterEvent](
            records=tuple(records[key] for key in sorted(records)),
            issues=tuple(issues),
        )

    async def find_recent_events(
        self, query: DisasterQuery, *, now: datetime
    ) -> ProviderBatch[DisasterEvent]:
        if query.disaster is not Disaster.VOLCANIC_ERUPTION:
            return ProviderBatch()
        batch = await self._discover(query, now=now, country=query.country)
        return ProviderBatch[DisasterEvent](
            records=tuple(
                record for record in batch.records if isinstance(record, DisasterEvent)
            ),
            issues=batch.issues,
        )

    async def find_worldwide_events(
        self, query: WorldwideDisasterQuery, *, now: datetime
    ) -> ProviderBatch[WorldwideDisasterEvent]:
        if query.disaster is not Disaster.VOLCANIC_ERUPTION or query.limit <= 0:
            return ProviderBatch()
        batch = await self._discover(query, now=now, country=None)
        records = tuple(
            record
            for record in batch.records
            if isinstance(record, WorldwideDisasterEvent)
        )
        return ProviderBatch[WorldwideDisasterEvent](
            records=tuple(
                record for record in records[: min(query.limit, _MAX_FEATURES)]
            ),
            issues=batch.issues,
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def _equivalent_duplicate(
    first: DisasterEvent | WorldwideDisasterEvent,
    second: DisasterEvent | WorldwideDisasterEvent,
) -> bool:
    """Treat repeated weekly fallback pages as one identity only when stable."""
    if (
        first.event_id != second.event_id
        or first.disaster != second.disaster
        or first.location != second.location
        or first.event_time != second.event_time
        or first.provider_ids != second.provider_ids
        or first.geometry is None
        or second.geometry is None
        or first.geometry.kind != second.geometry.kind
        or first.geometry.coordinates != second.geometry.coordinates
        or first.geometry.description != second.geometry.description
    ):
        return False
    return (
        first.source.source_id == second.source.source_id
        and first.source.publisher == second.source.publisher
        and first.source.title == second.source.title
        and first.source.published_at == second.source.published_at
        and first.source.updated_at == second.source.updated_at
        and first.source.retrieved_at == second.source.retrieved_at
        and first.source.authority == second.source.authority
        and first.source.snapshot_id == second.source.snapshot_id
        and first.measurements == second.measurements
    )
