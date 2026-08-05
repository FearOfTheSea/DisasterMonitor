"""USGS GeoJSON earthquake catalog adapter."""

from datetime import datetime, timedelta

import httpx

from disaster_monitor.application.disaster import (
    DisasterEvent,
    DisasterQuery,
    ProviderBatch,
    SourceReference,
)
from disaster_monitor.application.services.evidence_reconciliation import (
    normalize_timestamp,
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


class UsgsEarthquakeAdapter:
    """Find recent earthquake candidates from the documented USGS GeoJSON API."""

    provider_name = "USGS"

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 10.0,
        max_response_bytes: int = 1_000_000,
    ) -> None:
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = client is None
        self._max_response_bytes = max_response_bytes

    async def find_recent_events(
        self, query: DisasterQuery, *, now: datetime
    ) -> ProviderBatch[DisasterEvent]:
        starttime = query.date_from or now - timedelta(days=query.time_window_days)
        endtime = query.date_to or now
        params: dict[str, str | int | float | bool | None] = {
            "format": "geojson",
            "eventtype": "earthquake",
            "starttime": starttime.isoformat(),
            "endtime": endtime.isoformat(),
            "minlatitude": 20,
            "maxlatitude": 46,
            "minlongitude": 122,
            "maxlongitude": 154,
            "orderby": "time",
            "limit": 50,
            "includeallmagnitudes": "true",
            "includeallorigins": "true",
        }
        if query.magnitude is not None:
            params["minmagnitude"] = query.magnitude - 0.1
        payload = await get_json(
            self._client,
            USGS_QUERY_URL,
            params=params,
            max_bytes=self._max_response_bytes,
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
        for raw_feature in raw_features:
            if not isinstance(raw_feature, dict):
                raise DisasterProviderResponseError(
                    "The USGS response contained a malformed feature."
                )
            properties = raw_feature.get("properties")
            geometry = raw_feature.get("geometry")
            if not isinstance(properties, dict) or not isinstance(geometry, dict):
                raise DisasterProviderResponseError(
                    "The USGS response contained a malformed feature."
                )
            coordinates = geometry.get("coordinates")
            if not isinstance(coordinates, list) or len(coordinates) < 3:
                raise DisasterProviderResponseError(
                    "The USGS feature had invalid coordinates."
                )
            event_time = normalize_timestamp(properties.get("time"))
            event_id = _text(raw_feature.get("id"))
            if not event_id or event_time is None:
                raise DisasterProviderResponseError(
                    "The USGS feature lacked an event identifier or time."
                )
            try:
                longitude, latitude, depth_km = (
                    float(coordinates[0]),
                    float(coordinates[1]),
                    float(coordinates[2]),
                )
            except (TypeError, ValueError) as error:
                raise DisasterProviderResponseError(
                    "The USGS feature had non-numeric coordinates."
                ) from error
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
            )
            events.append(
                DisasterEvent(
                    event_id=f"usgs:{event_id}",
                    hazard="earthquake",
                    location=_text(properties.get("place")) or "Japan",
                    country="Japan",
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
                    is_aftershock="aftershock"
                    in _text(properties.get("title")).lower(),
                )
            )
        return ProviderBatch(records=tuple(events))

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
