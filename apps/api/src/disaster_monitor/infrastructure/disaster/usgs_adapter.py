"""Country-neutral USGS GeoJSON earthquake catalog adapter."""

from datetime import datetime, timedelta

import httpx

from disaster_monitor.application.disaster import (
    DisasterQuery,
    ProviderBatch,
    ProviderIssue,
)
from disaster_monitor.application.ports.geography import CountryCatalog
from disaster_monitor.application.services.evidence_reconciliation import (
    normalize_timestamp,
)
from disaster_monitor.domain.disaster import (
    BoundaryValidationQuality,
    DisasterEvent,
    Hazard,
    SourceAuthority,
    SourceReference,
)
from disaster_monitor.infrastructure.disaster.errors import (
    DisasterProviderResponseError,
)
from disaster_monitor.infrastructure.disaster.http import get_json

USGS_QUERY_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"


def _number(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


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


class UsgsEarthquakeAdapter:
    """Find country-validated earthquake candidates from USGS GeoJSON."""

    provider_name = "USGS"

    def __init__(
        self,
        *,
        geography: CountryCatalog,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 10.0,
        max_response_bytes: int = 1_000_000,
    ) -> None:
        self._geography = geography
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = client is None
        self._max_response_bytes = max_response_bytes

    def _parse_feature(
        self,
        raw_feature: object,
        query: DisasterQuery,
        *,
        now: datetime,
        index: int,
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
        if not self._geography.contains(query.country, latitude, longitude):
            return None, ProviderIssue(
                self.provider_name,
                f"{self.provider_name}: An event outside "
                f"{query.country.canonical_name} was excluded.",
                reason_code="country_mismatch",
                detail=f"feature[{index}] coordinate failed country validation",
            )
        url = _text(properties.get("url"))
        if not url.startswith("https://"):
            url = f"https://earthquake.usgs.gov/earthquakes/eventpage/{event_id}"
        updated_at = normalize_timestamp(properties.get("updated"))
        source = SourceReference(
            publisher="United States Geological Survey",
            title=_text(properties.get("title")) or "USGS earthquake event",
            canonical_url=url,
            published_at=event_time,
            updated_at=updated_at,
            retrieved_at=now,
            authority=SourceAuthority.SCIENTIFIC_AUTHORITY,
        )
        return (
            DisasterEvent(
                event_id=f"usgs:{event_id}",
                hazard=Hazard.EARTHQUAKE,
                location=(
                    _text(properties.get("place")) or query.country.canonical_name
                ),
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
            ),
            None,
        )

    async def find_recent_events(
        self, query: DisasterQuery, *, now: datetime
    ) -> ProviderBatch[DisasterEvent]:
        payload = await get_json(
            self._client,
            USGS_QUERY_URL,
            params=build_usgs_params(query, now=now),
            max_bytes=self._max_response_bytes,
            provider_name=self.provider_name,
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
            event, issue = self._parse_feature(raw_feature, query, now=now, index=index)
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

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
