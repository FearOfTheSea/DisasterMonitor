"""Official NHC/CPHC forecast track and uncertainty geometry."""

from __future__ import annotations

from datetime import datetime
from zipfile import BadZipFile

import httpx
from defusedxml import ElementTree

from disaster_monitor.application.disaster import (
    DisasterQuery,
    ProviderBatch,
    ProviderIssue,
    WorldwideDisasterEvent,
    WorldwideDisasterQuery,
)
from disaster_monitor.domain.disaster import (
    CorrelationStatus,
    CycloneMapLayer,
    Disaster,
    DisasterEvent,
    EventCoordinate,
    SituationReport,
    geographic_distance_km,
)
from disaster_monitor.infrastructure.disaster.errors import DisasterProviderError
from disaster_monitor.infrastructure.disaster.http import (
    SnapshotCapture,
    SourcePayloadRecorder,
    build_snapshot_capture,
    get_bytes,
    get_text,
)
from disaster_monitor.infrastructure.disaster.nhc_forecast_parsing import (
    _Candidate,
    _deduplicate_candidates,
    _eligible,
    _event_point,
    _extract_kml,
    _feed_source,
    _geometry_unavailable,
    _identity_issue,
    _invalid_product,
    _name_tokens,
    _normalized_name,
    _parse_cone,
    _parse_feed,
    _parse_track,
    _product_source,
    _products_unavailable,
    _provider_error,
)

_FEED_URLS = (
    "https://www.nhc.noaa.gov/gis-at.xml",
    "https://www.nhc.noaa.gov/gis-ep.xml",
    "https://www.nhc.noaa.gov/gis-cp.xml",
)
_RIGHTS_ID = "noaa-nws-public-domain"
_MAX_MATCH_DISTANCE_KM = 500.0


class NhcCycloneForecastAdapter:
    """Reconcile official NHC forecast products to one selected GDACS storm."""

    provider_name = "NOAA NHC/CPHC cyclone forecasts"
    source_id = "noaa-nhc-cyclone-forecast"
    allowed_hosts = frozenset({"www.nhc.noaa.gov"})

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        snapshot_recorder: SourcePayloadRecorder | None = None,
        timeout_seconds: float = 10.0,
        max_response_bytes: int = 1_000_000,
    ) -> None:
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = client is None
        self._snapshot_recorder = snapshot_recorder
        self._max_response_bytes = max_response_bytes

    async def get_situation_reports(
        self,
        event: DisasterEvent,
        query: DisasterQuery,
        *,
        now: datetime,
    ) -> ProviderBatch[SituationReport]:
        if not _eligible(event, query.disaster):
            return ProviderBatch()
        if event.country.alpha3_code != query.country.alpha3_code:
            return ProviderBatch()
        return await self._get_reports(
            event,
            now=now,
            countries=(query.country.canonical_name,),
            country_codes=(query.country.alpha3_code,),
        )

    async def get_worldwide_situation_reports(
        self,
        event: WorldwideDisasterEvent,
        query: WorldwideDisasterQuery,
        *,
        now: datetime,
    ) -> ProviderBatch[SituationReport]:
        if not _eligible(event, query.disaster):
            return ProviderBatch()
        return await self._get_reports(
            event,
            now=now,
            countries=(),
            country_codes=(),
        )

    async def _get_reports(
        self,
        event: DisasterEvent | WorldwideDisasterEvent,
        *,
        now: datetime,
        countries: tuple[str, ...],
        country_codes: tuple[str, ...],
    ) -> ProviderBatch[SituationReport]:
        event_point = _event_point(event)
        if event_point is None:
            return ProviderBatch(issues=(_geometry_unavailable(),))

        candidates: list[_Candidate] = []
        issues: list[ProviderIssue] = []
        for feed_url in _FEED_URLS:
            capture = self._capture(feed_url, now)
            feed_payload = await get_text(
                self._client,
                feed_url,
                capture=capture,
                allowed_hosts=self.allowed_hosts,
                max_bytes=self._max_response_bytes,
                provider_name=self.provider_name,
            )
            parsed, feed_issues = _parse_feed(feed_payload, feed_url, capture)
            candidates.extend(parsed)
            issues.extend(feed_issues)

        candidates = list(_deduplicate_candidates(candidates))
        name_tokens = _name_tokens(event.source.title)
        matches = [
            candidate
            for candidate in candidates
            if _normalized_name(candidate.name) in name_tokens
            and geographic_distance_km(
                event_point,
                EventCoordinate(candidate.latitude, candidate.longitude),
            )
            <= _MAX_MATCH_DISTANCE_KM
        ]
        if len(matches) != 1:
            issues.append(_identity_issue(ambiguous=len(matches) > 1))
            return ProviderBatch(issues=tuple(issues))

        candidate = matches[0]
        if not candidate.products:
            issues.append(_products_unavailable())
            return ProviderBatch(issues=tuple(issues))

        layers: list[CycloneMapLayer] = []
        for product in candidate.products:
            capture = self._capture(product.url, now)
            try:
                product_payload = await get_bytes(
                    self._client,
                    product.url,
                    capture=capture,
                    allowed_hosts=self.allowed_hosts,
                    max_bytes=self._max_response_bytes,
                    provider_name=self.provider_name,
                )
                kml = _extract_kml(product_payload)
                source = _product_source(candidate, product, capture, now)
                if product.kind == "track":
                    layer, product_issues = _parse_track(
                        kml, candidate, product, source
                    )
                else:
                    layer, product_issues = _parse_cone(kml, candidate, product, source)
                issues.extend(product_issues)
                if layer is not None:
                    layers.append(layer)
            except DisasterProviderError as error:
                issues.append(_provider_error(product.kind, error))
            except (BadZipFile, ElementTree.ParseError, ValueError) as error:
                issues.append(_invalid_product(product.kind, error))

        if not layers:
            return ProviderBatch(issues=tuple(issues))

        layers.sort(key=lambda item: item.semantic_role.value)
        source = _feed_source(candidate, now)
        distance = geographic_distance_km(
            event_point, EventCoordinate(candidate.latitude, candidate.longitude)
        )
        report = SituationReport(
            source=source,
            narrative=(
                f"NOAA NHC/CPHC advisory products for {candidate.name} "
                f"({candidate.storm_id}) were reconciled by unique storm name and "
                f"source-backed center proximity ({distance:.0f} km). Forecast and "
                "uncertainty layers are advisory products, not observed footprints."
            ),
            event_id=event.event_id,
            correlation=CorrelationStatus.MATCHED,
            reported_event_time=event.event_time,
            locations=(event.location,),
            countries=countries,
            country_codes=country_codes,
            disaster=Disaster.TROPICAL_CYCLONE,
            provider_event_ids=(f"atcf:{candidate.storm_id}",),
            supplemental_geometry=tuple(layers),
        )
        return ProviderBatch((report,), tuple(issues))

    def _capture(self, url: str, now: datetime) -> SnapshotCapture | None:
        return build_snapshot_capture(
            self._snapshot_recorder,
            source_id=self.source_id,
            parameters={"url": url},
            rights_id=_RIGHTS_ID,
            retrieved_at=now,
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
