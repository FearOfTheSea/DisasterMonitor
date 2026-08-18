"""Country-neutral USGS GeoJSON earthquake catalog adapter."""

import re
from datetime import datetime, timedelta

import httpx

from disaster_monitor.application.disaster import (
    DisasterQuery,
    GlobalDisasterEvent,
    GlobalEarthquakeQuery,
    GlobalEventSelection,
    ProviderBatch,
    ProviderIssue,
    WorldwideDisasterQuery,
)
from disaster_monitor.application.ports.geography import CountryCatalog
from disaster_monitor.application.services.evidence_reconciliation import (
    normalize_timestamp,
)
from disaster_monitor.domain.disaster import (
    BoundaryValidationQuality,
    Country,
    DisasterEvent,
    EventGeographyStatus,
    Hazard,
    SourceAuthority,
    SourceReference,
)
from disaster_monitor.infrastructure.disaster.errors import (
    DisasterProviderResponseError,
)
from disaster_monitor.infrastructure.disaster.http import (
    SourcePayloadRecorder,
    build_snapshot_capture,
    get_json,
    validate_network_target,
)

USGS_QUERY_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"
_MAX_OFFSHORE_ASSOCIATION_DISTANCE_KM = 100.0


def _number(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _place_mentions_country(place: str, country: Country) -> bool:
    """Require explicit provider place text before assigning an offshore event."""
    terms = (country.canonical_name, country.alpha3_code, *country.aliases)
    return any(
        re.search(rf"(?<!\w){re.escape(term)}(?!\w)", place, re.IGNORECASE)
        for term in terms
        if term
    )


def build_usgs_params(
    query: DisasterQuery, *, now: datetime
) -> dict[str, str | int | float | bool | None]:
    """Build one bounded USGS query from normalized country geography."""
    starttime = query.date_from or now - timedelta(days=query.time_window_days)
    endtime = query.date_to or now
    generic_query = not any(
        (
            query.event_identifier,
            query.date_from,
            query.date_to,
            query.prefecture,
            query.city,
            query.latitude is not None and query.longitude is not None,
            query.magnitude is not None,
        )
    )
    area = query.country.geographic_area
    min_latitude = area.min_latitude
    max_latitude = area.max_latitude
    min_longitude = area.min_longitude
    max_longitude = area.max_longitude
    if query.latitude is not None and query.longitude is not None:
        min_latitude = max(min_latitude, query.latitude - 2)
        max_latitude = min(max_latitude, query.latitude + 2)
        min_longitude = max(min_longitude, query.longitude - 2)
        max_longitude = min(max_longitude, query.longitude + 2)
    params: dict[str, str | int | float | bool | None] = {
        "format": "geojson",
        "eventtype": "earthquake",
        "starttime": starttime.isoformat(),
        "endtime": endtime.isoformat(),
        "minlatitude": min_latitude,
        "maxlatitude": max_latitude,
        "minlongitude": min_longitude,
        "maxlongitude": max_longitude,
        "orderby": "magnitude" if generic_query else "time",
        "limit": 50,
    }
    if generic_query:
        params["minmagnitude"] = 4.5
    if query.magnitude is not None:
        params["minmagnitude"] = query.magnitude - 0.1
    return params


def build_global_usgs_params(
    query: GlobalEarthquakeQuery | WorldwideDisasterQuery, *, now: datetime
) -> dict[str, str | int | float]:
    """Build a bounded worldwide query with an explicit ranking policy."""
    selection = (
        query.selection.value
        if isinstance(query.selection, GlobalEventSelection)
        else query.selection
    )
    return {
        "format": "geojson",
        "eventtype": "earthquake",
        "starttime": (now - timedelta(days=query.time_window_days)).isoformat(),
        "endtime": now.isoformat(),
        "minmagnitude": query.minimum_magnitude or 4.5,
        "orderby": (
            "magnitude" if selection == GlobalEventSelection.STRONGEST else "time"
        ),
        "limit": query.limit,
    }


class UsgsEarthquakeAdapter:
    """Find country-validated earthquake candidates from USGS GeoJSON."""

    provider_name = "USGS"
    source_id = "usgs-earthquakes"
    allowed_hosts = frozenset({"earthquake.usgs.gov"})

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
        self._max_response_bytes = max_response_bytes
        self._snapshot_recorder = snapshot_recorder

    def _parse_feature(
        self,
        raw_feature: object,
        query: DisasterQuery,
        *,
        now: datetime,
        index: int,
        snapshot_id: str | None,
    ) -> tuple[DisasterEvent | None, ProviderIssue | None]:
        try:
            if not isinstance(raw_feature, dict):
                raise ValueError("feature is not an object")
            properties = raw_feature.get("properties")
            geometry = raw_feature.get("geometry")
            if not isinstance(properties, dict) or not isinstance(geometry, dict):
                raise ValueError("properties or geometry is missing")
            coordinates = geometry.get("coordinates")
            if not isinstance(coordinates, list) or len(coordinates) < 3:
                raise ValueError("coordinates are invalid")
            event_time = normalize_timestamp(properties.get("time"))
            event_id = _text(raw_feature.get("id"))
            if not event_id or event_time is None:
                raise ValueError("identifier or event time is missing")
            longitude, latitude, depth_km = (
                float(coordinates[0]),
                float(coordinates[1]),
                float(coordinates[2]),
            )
        except (TypeError, ValueError, OverflowError) as error:
            return None, ProviderIssue(
                self.provider_name,
                f"{self.provider_name}: A malformed event record was skipped.",
                reason_code="invalid_record",
                detail=f"feature[{index}]: {error}",
            )
        place = _text(properties.get("place"))
        geography_status = EventGeographyStatus.IN_COUNTRY
        if not self._geography.contains(query.country, latitude, longitude):
            distance_km = query.country.geographic_area.distance_to_boundary_km(
                latitude, longitude
            )
            if (
                distance_km is None
                or distance_km > _MAX_OFFSHORE_ASSOCIATION_DISTANCE_KM
                or not _place_mentions_country(place, query.country)
            ):
                return None, ProviderIssue(
                    self.provider_name,
                    f"{self.provider_name}: An event outside "
                    f"{query.country.canonical_name} was excluded.",
                    reason_code="country_mismatch",
                    detail=f"feature[{index}] coordinate failed country validation",
                )
            geography_status = EventGeographyStatus.COUNTRY_ASSOCIATED_OFFSHORE
        url = _text(properties.get("url"))
        try:
            validate_network_target(url, self.allowed_hosts)
        except DisasterProviderResponseError:
            url = f"https://earthquake.usgs.gov/earthquakes/eventpage/{event_id}"
        updated_at = normalize_timestamp(properties.get("updated"))
        source = SourceReference(
            source_id=self.source_id,
            publisher="United States Geological Survey",
            title=_text(properties.get("title")) or "USGS earthquake event",
            canonical_url=url,
            published_at=event_time,
            updated_at=updated_at,
            retrieved_at=now,
            authority=SourceAuthority.SCIENTIFIC_AUTHORITY,
            snapshot_id=snapshot_id,
        )
        return (
            DisasterEvent(
                event_id=f"usgs:{event_id}",
                hazard=Hazard.EARTHQUAKE,
                location=(place or query.country.canonical_name),
                country=query.country,
                event_time=event_time,
                source=source,
                latitude=latitude,
                longitude=longitude,
                magnitude=_number(properties.get("mag")),
                magnitude_type=_text(properties.get("magType")) or None,
                intensity=(
                    f"MMI {properties['mmi']}"
                    if isinstance(properties.get("mmi"), (int, float))
                    else None
                ),
                depth_km=depth_km,
                significance=_number(properties.get("sig")),
                is_aftershock="aftershock" in _text(properties.get("title")).lower(),
                provider_ids=(f"usgs:{event_id}",),
                geography_status=geography_status,
            ),
            None,
        )

    def _parse_global_feature(
        self,
        raw_feature: object,
        *,
        now: datetime,
        index: int,
        snapshot_id: str | None,
    ) -> tuple[GlobalDisasterEvent | None, ProviderIssue | None]:
        try:
            if not isinstance(raw_feature, dict):
                raise ValueError("feature is not an object")
            properties = raw_feature.get("properties")
            geometry = raw_feature.get("geometry")
            if not isinstance(properties, dict) or not isinstance(geometry, dict):
                raise ValueError("properties or geometry is missing")
            coordinates = geometry.get("coordinates")
            if not isinstance(coordinates, list) or len(coordinates) < 3:
                raise ValueError("coordinates are invalid")
            event_time = normalize_timestamp(properties.get("time"))
            event_id = _text(raw_feature.get("id"))
            if not event_id or event_time is None:
                raise ValueError("identifier or event time is missing")
            longitude, latitude, depth_km = (
                float(coordinates[0]),
                float(coordinates[1]),
                float(coordinates[2]),
            )
            if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
                raise ValueError("coordinates are outside the world extent")
            if depth_km < 0:
                raise ValueError("depth is negative")
        except (TypeError, ValueError, OverflowError) as error:
            return None, ProviderIssue(
                self.provider_name,
                f"{self.provider_name}: A malformed event record was skipped.",
                reason_code="invalid_record",
                detail=f"feature[{index}]: {error}",
            )
        url = _text(properties.get("url"))
        try:
            validate_network_target(url, self.allowed_hosts)
        except DisasterProviderResponseError:
            url = f"https://earthquake.usgs.gov/earthquakes/eventpage/{event_id}"
        source = SourceReference(
            source_id=self.source_id,
            publisher="United States Geological Survey",
            title=_text(properties.get("title")) or "USGS earthquake event",
            canonical_url=url,
            published_at=event_time,
            updated_at=normalize_timestamp(properties.get("updated")),
            retrieved_at=now,
            authority=SourceAuthority.SCIENTIFIC_AUTHORITY,
            snapshot_id=snapshot_id,
        )
        return (
            GlobalDisasterEvent(
                event_id=f"usgs:{event_id}",
                hazard=Hazard.EARTHQUAKE,
                location=_text(properties.get("place")) or "Worldwide earthquake",
                event_time=event_time,
                source=source,
                latitude=latitude,
                longitude=longitude,
                magnitude=_number(properties.get("mag")),
                magnitude_type=_text(properties.get("magType")) or None,
                intensity=(
                    f"MMI {properties['mmi']}"
                    if isinstance(properties.get("mmi"), (int, float))
                    else None
                ),
                depth_km=depth_km,
                significance=_number(properties.get("sig")),
                provider_ids=(f"usgs:{event_id}",),
            ),
            None,
        )

    async def find_recent_events(
        self, query: DisasterQuery, *, now: datetime
    ) -> ProviderBatch[DisasterEvent]:
        capture = build_snapshot_capture(
            self._snapshot_recorder,
            source_id=self.source_id,
            parameters={
                "country": query.country.alpha3_code,
                "from": (
                    query.date_from or now - timedelta(days=query.time_window_days)
                ).isoformat(),
                "to": (query.date_to or now).isoformat(),
                "event": query.event_identifier or "",
            },
            rights_id="usgs-earthquake-api-terms-2026-08",
            retrieved_at=now,
        )
        payload = await get_json(
            self._client,
            USGS_QUERY_URL,
            allowed_hosts=self.allowed_hosts,
            params=build_usgs_params(query, now=now),
            max_bytes=self._max_response_bytes,
            provider_name=self.provider_name,
            capture=capture,
        )
        if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection":
            raise DisasterProviderResponseError(
                "The USGS response was not a GeoJSON FeatureCollection."
            )
        raw_features = payload.get("features")
        if not isinstance(raw_features, list):
            raise DisasterProviderResponseError(
                "The USGS GeoJSON response had no feature list."
            )
        events: list[DisasterEvent] = []
        issues: list[ProviderIssue] = []
        for index, raw_feature in enumerate(raw_features):
            event, issue = self._parse_feature(
                raw_feature,
                query,
                now=now,
                index=index,
                snapshot_id=capture.snapshot.snapshot_id
                if capture and capture.snapshot
                else None,
            )
            if event is not None:
                events.append(event)
            if issue is not None:
                issues.append(issue)
        if (
            events
            and query.country.geographic_area.validation_quality
            == BoundaryValidationQuality.BOUNDING_BOX
        ):
            issues.append(
                ProviderIssue(
                    self.provider_name,
                    f"{self.provider_name}: Country membership was validated only "
                    "against an approximate bounding box.",
                    reason_code="country_membership_approximate",
                )
            )
        if not events and not issues:
            issues.append(
                ProviderIssue(
                    self.provider_name,
                    f"{self.provider_name}: The provider returned no matching records.",
                    reason_code="empty_result",
                )
            )
        return ProviderBatch(records=tuple(events), issues=tuple(issues))

    async def find_worldwide_events(
        self, query: WorldwideDisasterQuery, *, now: datetime
    ) -> ProviderBatch[GlobalDisasterEvent]:
        """Find bounded worldwide events without assigning a synthetic country."""
        capture = build_snapshot_capture(
            self._snapshot_recorder,
            source_id=self.source_id,
            parameters={
                "scope": "worldwide",
                "selection": (
                    query.selection.value
                    if isinstance(query.selection, GlobalEventSelection)
                    else query.selection
                ),
                "from": (now - timedelta(days=query.time_window_days)).isoformat(),
                "to": now.isoformat(),
                "minimum_magnitude": str(query.minimum_magnitude),
            },
            rights_id="usgs-earthquake-api-terms-2026-08",
            retrieved_at=now,
        )
        payload = await get_json(
            self._client,
            USGS_QUERY_URL,
            allowed_hosts=self.allowed_hosts,
            params=build_global_usgs_params(query, now=now),
            max_bytes=self._max_response_bytes,
            provider_name=self.provider_name,
            capture=capture,
        )
        if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection":
            raise DisasterProviderResponseError(
                "The USGS response was not a GeoJSON FeatureCollection."
            )
        raw_features = payload.get("features")
        if not isinstance(raw_features, list):
            raise DisasterProviderResponseError(
                "The USGS GeoJSON response had no feature list."
            )
        events: list[GlobalDisasterEvent] = []
        issues: list[ProviderIssue] = []
        for index, raw_feature in enumerate(raw_features):
            event, issue = self._parse_global_feature(
                raw_feature,
                now=now,
                index=index,
                snapshot_id=(
                    capture.snapshot.snapshot_id
                    if capture and capture.snapshot
                    else None
                ),
            )
            if event is not None:
                events.append(event)
            if issue is not None:
                issues.append(issue)
        if not events and not issues:
            issues.append(
                ProviderIssue(
                    self.provider_name,
                    f"{self.provider_name}: The provider returned no matching records.",
                    reason_code="empty_result",
                )
            )
        return ProviderBatch(tuple(events), tuple(issues))

    async def find_global_earthquakes(
        self, query: GlobalEarthquakeQuery, *, now: datetime
    ) -> ProviderBatch[GlobalDisasterEvent]:
        """Compatibility wrapper for the former earthquake-specific port."""
        return await self.find_worldwide_events(
            WorldwideDisasterQuery(
                hazard=Hazard.EARTHQUAKE,
                selection=query.selection.value,
                time_window_days=query.time_window_days,
                minimum_magnitude=query.minimum_magnitude,
                limit=query.limit,
            ),
            now=now,
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
