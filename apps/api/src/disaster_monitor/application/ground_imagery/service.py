"""Orchestrate region planning, catalog discovery, and deterministic selection."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from disaster_monitor.application.ground_imagery import identifiers as _identifiers
from disaster_monitor.application.ground_imagery.artifact_workflow import (
    GroundImageryArtifactWorkflow,
)
from disaster_monitor.application.ground_imagery.catalog_search import (
    GroundImageryCatalogSearcher,
)
from disaster_monitor.application.ground_imagery.errors import (
    GroundImageryError,
    GroundImageryIncidentNotFound,
    GroundImageryRequestNotFound,
)
from disaster_monitor.application.ground_imagery.manifest import (
    build_manifest,
    request_has_selection,
)
from disaster_monitor.application.ground_imagery.models import (
    GroundImageryRequest,
    GroundImageryRequestInput,
    GroundImageryRequestState,
    SensorSearchStatus,
)
from disaster_monitor.application.ground_imagery.request_indexes import (
    GroundImageryRequestIndexes,
)
from disaster_monitor.application.ground_imagery.resolve_region import (
    GroundImageryRegionResolver,
    RegionResolutionState,
)
from disaster_monitor.application.ground_imagery.select_observations import (
    GroundImagerySelection,
    SelectionReason,
    SelectionResult,
    SensorSelection,
    select_observations,
)
from disaster_monitor.application.ground_imagery.temporal_policy import (
    build_temporal_plan,
    watch_check_interval,
)
from disaster_monitor.application.ports.ground_imagery.artifacts import (
    ImageryArtifactStore,
    StoredArtifact,
)
from disaster_monitor.application.ports.ground_imagery.catalog import (
    GroundImageryCatalog,
)
from disaster_monitor.application.ports.ground_imagery.incidents import (
    IncidentImageryContextReader,
)
from disaster_monitor.application.ports.ground_imagery.rendering import (
    GroundImageryRasterValidator,
    GroundImageryRenderer,
    GroundImageryTileRenderer,
)
from disaster_monitor.application.ports.ground_imagery.repository import (
    GroundImageryRequestStore,
)
from disaster_monitor.domain.imagery.observations import (
    Observation,
    Sensor,
    TemporalRole,
)
from disaster_monitor.domain.imagery.regions import MultiPolygon


@dataclass(frozen=True, slots=True)
class GroundImageryObservationPage:
    observations: tuple[Observation, ...]
    next_cursor: str | None
    total: int


class GroundImageryService:
    """The application boundary for a bounded event-focused imagery request."""

    def __init__(
        self,
        context_reader: IncidentImageryContextReader,
        region_resolver: GroundImageryRegionResolver,
        catalog: GroundImageryCatalog,
        store: GroundImageryRequestStore,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        maximum_catalog_items: int = 500,
        renderer: GroundImageryRenderer | None = None,
        raster_validator: GroundImageryRasterValidator | None = None,
        artifact_store: ImageryArtifactStore | None = None,
        tile_renderer: GroundImageryTileRenderer | None = None,
        enabled: bool = True,
    ) -> None:
        self._context_reader = context_reader
        self._region_resolver = region_resolver
        self._catalog = catalog
        self._catalog_searcher = GroundImageryCatalogSearcher(
            catalog, maximum_catalog_items=maximum_catalog_items
        )
        self._store = store
        self._clock = clock
        self._artifact_workflow = GroundImageryArtifactWorkflow(
            region_resolver,
            clock=clock,
            renderer=renderer,
            raster_validator=raster_validator,
            artifact_store=artifact_store,
            tile_renderer=tile_renderer,
        )
        self._enabled = enabled
        self._indexes = GroundImageryRequestIndexes()

    async def create_request(
        self,
        request_input: GroundImageryRequestInput,
        *,
        request_id_override: str | None = None,
        request_version: int = 1,
    ) -> GroundImageryRequest:
        """Resolve the incident and search both sensors independently."""
        if not self._enabled:
            raise GroundImageryError(
                "Ground imagery is disabled by server configuration."
            )
        if request_input.idempotency_key is not None:
            existing_id = self._indexes.request_for_idempotency(
                request_input.owner_scope, request_input.idempotency_key
            )
            if existing_id is not None:
                existing = await self._store.get_request(existing_id)
                if existing is not None:
                    self._indexes.index(existing)
                    return existing
            durable_id = _identifiers.request_id(request_input)
            existing = await self._store.get_request(durable_id)
            if existing is not None:
                self._indexes.remember(request_input, durable_id)
                self._indexes.index(existing)
                return existing

        context = await self._context_reader.get_imagery_context(
            request_input.incident_id
        )
        if context is None:
            raise GroundImageryIncidentNotFound(
                "The selected incident is no longer available for imagery planning."
            )
        now = self._clock()
        region = await self._region_resolver.resolve_async(
            context,
            user_region=request_input.user_region,
            context_margin_km=request_input.context_margin_km,
            fallback_radius_km=request_input.fallback_radius_km,
        )
        onset = request_input.onset_override or context.onset
        plan = build_temporal_plan(
            onset=onset,
            reference_time=request_input.reference_time,
            disaster=context.disaster,
            activity_status=context.activity_status,
            impact_end=context.impact_end,
        )
        request_id = request_id_override or _identifiers.request_id(request_input)
        if request_input.idempotency_key is None and request_id_override is None:
            request_id = f"ground-imagery:{uuid4().hex}"
        if region.state is not RegionResolutionState.RESOLVED or region.region is None:
            request = GroundImageryRequest(
                request_id=request_id,
                request_version=request_version,
                incident_id=context.incident_id,
                disaster=context.disaster,
                reference_time=request_input.reference_time,
                requested_sensors=request_input.sensors,
                region_resolution=region,
                temporal_plan=plan,
                candidates=(),
                search_status=tuple(
                    SensorSearchStatus(
                        sensor, 0, False, failure_code=region.reason_code
                    )
                    for sensor in request_input.sensors
                ),
                selection=None,
                state=GroundImageryRequestState.NEEDS_REGION,
                reason_codes=_identifiers.unique_reasons(
                    (region.reason_code or "needs_region",)
                ),
                created_at=now,
                updated_at=now,
                owner_scope=request_input.owner_scope,
            )
            await self._store.save_request(request)
            self._indexes.remember(request_input, request_id)
            self._indexes.index(request)
            return request

        search = await self._catalog_searcher.search(
            region.region.inspection,
            plan,
            request_input.sensors,
        )
        candidates_by_sensor = search.candidates
        statuses = search.statuses
        search_reasons = search.reason_codes
        selection = select_observations(
            plan,
            candidates_by_sensor,
            disaster=context.disaster,
            scan_complete={
                (status.sensor, role): status.scan_complete
                for status in statuses
                for role in {
                    window.role
                    for window in plan.windows
                    if window.sensor is status.sensor
                }
            },
        )
        reasons = list(search_reasons)
        for sensor in request_input.sensors:
            for outcome in selection.for_sensor(sensor).selections:
                if outcome.reason is not SelectionReason.SELECTED:
                    reasons.append(outcome.reason.value)
        successful_sensors = sum(
            selection.for_sensor(sensor).has_observation
            for sensor in request_input.sensors
        )
        state = (
            GroundImageryRequestState.READY
            if successful_sensors == len(request_input.sensors)
            else GroundImageryRequestState.PARTIAL
        )
        request = GroundImageryRequest(
            request_id=request_id,
            request_version=request_version,
            incident_id=context.incident_id,
            disaster=context.disaster,
            reference_time=request_input.reference_time,
            requested_sensors=request_input.sensors,
            region_resolution=region,
            temporal_plan=plan,
            candidates=tuple(
                sorted(
                    (item for items in candidates_by_sensor.values() for item in items),
                    key=lambda item: (
                        item.sensor.value,
                        item.capture.start,
                        item.identity.stable_key,
                    ),
                )
            ),
            search_status=tuple(statuses),
            selection=selection,
            state=state,
            reason_codes=_identifiers.unique_reasons(reasons),
            created_at=now,
            updated_at=now,
            owner_scope=request_input.owner_scope,
        )
        await self._store.save_request(request)
        self._indexes.remember(request_input, request_id)
        self._indexes.index(request)
        return request

    async def get_request(self, request_id: str) -> GroundImageryRequest:
        request = await self._store.get_request(request_id)
        if request is None:
            raise GroundImageryRequestNotFound("The imagery request was not found.")
        return request

    async def observations(
        self,
        request_id: str,
        *,
        sensor: Sensor | None = None,
        cursor: int = 0,
        limit: int = 50,
    ) -> GroundImageryObservationPage:
        if not 0 <= cursor <= 500:
            raise ValueError("The imagery observation cursor is outside its bounds.")
        if not 1 <= limit <= 100:
            raise ValueError(
                "The imagery observation page size must be between 1 and 100."
            )
        request = await self.get_request(request_id)
        items = request.observations_for(sensor)
        page = items[cursor : cursor + limit]
        next_cursor = str(cursor + limit) if cursor + limit < len(items) else None
        return GroundImageryObservationPage(page, next_cursor, len(items))

    async def cancel(self, request_id: str) -> GroundImageryRequest:
        request = await self.get_request(request_id)
        if request.state in {
            GroundImageryRequestState.READY,
            GroundImageryRequestState.PARTIAL,
            GroundImageryRequestState.NEEDS_REGION,
            GroundImageryRequestState.FAILED,
            GroundImageryRequestState.CANCELLED,
        }:
            if request.state is not GroundImageryRequestState.CANCELLED:
                request = replace(
                    request,
                    state=GroundImageryRequestState.CANCELLED,
                    updated_at=self._clock(),
                    reason_codes=_identifiers.unique_reasons(
                        (*request.reason_codes, "cancelled")
                    ),
                )
                await self._store.save_request(request)
            return request
        request = replace(
            request,
            state=GroundImageryRequestState.CANCELLED,
            updated_at=self._clock(),
            reason_codes=_identifiers.unique_reasons(
                (*request.reason_codes, "cancelled")
            ),
        )
        await self._store.save_request(request)
        return request

    async def set_watch(
        self,
        request_id: str,
        *,
        enabled: bool,
        interval_seconds: int | None = None,
    ) -> GroundImageryRequest:
        request = await self.get_request(request_id)
        if interval_seconds is not None and not 3_600 <= interval_seconds <= 86_400:
            raise ValueError(
                "Imagery watch intervals must be between one and 24 hours."
            )
        interval = interval_seconds
        now = self._clock()
        if enabled and interval is None:
            cadence = watch_check_interval(request.created_at, now)
            interval = None if cadence is None else int(cadence.total_seconds())
        updated = replace(
            request,
            watch_enabled=enabled,
            watch_interval_seconds=interval,
            next_check_at=(
                None
                if not enabled or interval is None
                else now.replace(microsecond=0) + timedelta(seconds=interval)
            ),
            updated_at=now,
        )
        await self._store.save_request(updated)
        self._indexes.index(updated)
        return updated

    async def replace_region(
        self,
        request_id: str,
        region: MultiPolygon,
        *,
        context_margin_km: float | None = None,
    ) -> GroundImageryRequest:
        """Create a new immutable region version for the same request identity."""
        current = await self.get_request(request_id)
        refreshed = await self.create_request(
            GroundImageryRequestInput(
                incident_id=current.incident_id,
                reference_time=current.reference_time,
                sensors=current.requested_sensors,
                user_region=region,
                context_margin_km=context_margin_km,
                owner_scope=current.owner_scope,
                onset_override=current.temporal_plan.onset,
            ),
            request_id_override=current.request_id,
            request_version=current.request_version + 1,
        )
        old_region = current.region_resolution.region
        new_region = refreshed.region_resolution.region
        if new_region is not None:
            new_region = replace(
                new_region,
                region_id=old_region.region_id
                if old_region is not None
                else new_region.region_id,
                version=old_region.version + 1 if old_region is not None else 1,
                parent_region_id=old_region.region_id
                if old_region is not None
                else None,
            )
            refreshed = replace(
                refreshed,
                region_resolution=replace(
                    refreshed.region_resolution, region=new_region
                ),
            )
            await self._store.save_request(refreshed)
        return refreshed

    async def select_observation(
        self,
        request_id: str,
        *,
        sensor: Sensor,
        role: str,
        observation_id: str,
    ) -> GroundImageryRequest:
        """Pin a catalogued candidate without changing its source identity."""
        request = await self.get_request(request_id)
        if request.selection is None:
            raise ValueError("This imagery request has no catalog selection to change.")
        try:
            temporal_role = TemporalRole(role)
        except ValueError as error:
            raise ValueError("The imagery selection role is unsupported.") from error
        candidate = next(
            (
                item
                for item in request.candidates
                if item.sensor is sensor and item.observation_id == observation_id
            ),
            None,
        )
        if candidate is None:
            raise ValueError(
                "The requested observation is not in this imagery request."
            )
        sensor_selection = request.selection.for_sensor(sensor)
        current = sensor_selection.for_role(temporal_role)
        alternatives = current.alternatives + (
            (current.observation,) if current.observation is not None else ()
        )
        updated_outcome = GroundImagerySelection(
            role=temporal_role,
            observation=candidate,
            reason=SelectionReason.SELECTED,
            explanation="The operator selected this catalogued acquisition.",
            age_class=current.age_class,
            alternatives=tuple(
                item
                for item in alternatives
                if item.observation_id != candidate.observation_id
            ),
        )
        updated_sensor = SensorSelection(
            sensor=sensor,
            selections=tuple(
                updated_outcome if item.role is temporal_role else item
                for item in sensor_selection.selections
            ),
        )
        updated_selection = SelectionResult(
            plan=request.selection.plan,
            sensors=tuple(
                updated_sensor if item.sensor is sensor else item
                for item in request.selection.sensors
            ),
        )
        updated = replace(
            request,
            selection=updated_selection,
            updated_at=self._clock(),
            reason_codes=tuple(
                reason
                for reason in request.reason_codes
                if reason != current.reason.value
            ),
        )
        await self._store.save_request(updated)
        self._indexes.index(updated)
        return updated

    async def prepare_selection(
        self,
        request_id: str,
        *,
        sensor: Sensor,
        role: str,
        overview: bool = True,
        output_kind: str | None = None,
    ) -> GroundImageryRequest:
        """Render and publish one selected acquisition as an immutable artifact."""
        request = await self.get_request(request_id)
        updated = await self._artifact_workflow.prepare(
            request,
            sensor=sensor,
            role=role,
            overview=overview,
            output_kind=output_kind,
        )
        await self._store.save_request(updated)
        return updated

    async def read_artifact(
        self, artifact_id: str
    ) -> tuple[StoredArtifact, bytes] | None:
        return await self._artifact_workflow.read_artifact(artifact_id)

    async def render_tile(self, artifact_id: str, zoom: int, x: int, y: int) -> bytes:
        return await self._artifact_workflow.render_tile(artifact_id, zoom, x, y)

    def readiness(self) -> dict[str, object]:
        """Return actionable provider/artifact readiness without probing upstream."""
        if not self._enabled:
            return {"state": "disabled", "detail": "Ground imagery is disabled."}
        return self._artifact_workflow.readiness()

    async def refresh(self, request_id: str) -> GroundImageryRequest:
        """Re-run discovery for the same request identity and increment its version."""
        current = await self.get_request(request_id)
        context = await self._context_reader.get_imagery_context(current.incident_id)
        if context is None:
            raise GroundImageryIncidentNotFound(
                "The selected incident is no longer available for imagery planning."
            )
        input_value = GroundImageryRequestInput(
            incident_id=current.incident_id,
            reference_time=current.reference_time,
            sensors=current.requested_sensors,
            user_region=(
                current.region_resolution.region.inspection
                if current.region_resolution.region is not None
                else None
            ),
            context_margin_km=(
                0 if current.region_resolution.region is not None else None
            ),
            owner_scope=current.owner_scope,
            onset_override=current.temporal_plan.onset,
        )
        refreshed = await self.create_request(
            input_value,
            request_id_override=current.request_id,
            request_version=current.request_version + 1,
        )
        refreshed = replace(
            refreshed,
            region_resolution=(
                current.region_resolution
                if current.region_resolution.region is not None
                else refreshed.region_resolution
            ),
            watch_enabled=current.watch_enabled,
            watch_interval_seconds=current.watch_interval_seconds,
            next_check_at=current.next_check_at,
        )
        await self._store.save_request(refreshed)
        self._indexes.index(refreshed)
        return refreshed

    async def manifest(self, request_id: str) -> dict[str, object]:
        """Return credential-free provenance for the current immutable selection."""
        request = await self.get_request(request_id)
        return build_manifest(request)

    async def manifest_for_selection(
        self, selection_id_value: str
    ) -> dict[str, object]:
        """Resolve a stable selection manifest without exposing provider credentials."""
        request_id = self._indexes.request_for_selection(selection_id_value)
        request = (
            None if request_id is None else await self._store.get_request(request_id)
        )
        if request is None:
            request = await self._store.get_request_for_selection(selection_id_value)
        if request is None:
            raise GroundImageryRequestNotFound(
                "The imagery selection manifest was not found."
            )
        if not any(
            item.selection_id == selection_id_value for item in request.artifacts
        ) and not request_has_selection(request, selection_id_value):
            raise GroundImageryRequestNotFound(
                "The imagery selection manifest was not found."
            )
        return build_manifest(request)

    async def aclose(self) -> None:
        await self._catalog.aclose()
        await self._region_resolver.aclose()
        await self._artifact_workflow.aclose()
