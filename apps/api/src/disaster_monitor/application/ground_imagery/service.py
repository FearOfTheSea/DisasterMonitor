"""Orchestrate region planning, catalog discovery, and deterministic selection."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime

from disaster_monitor.application.ground_imagery import identifiers as _identifiers
from disaster_monitor.application.ground_imagery.artifact_access import (
    GroundImageryArtifactAccess,
)
from disaster_monitor.application.ground_imagery.artifact_workflow import (
    GroundImageryArtifactWorkflow,
)
from disaster_monitor.application.ground_imagery.catalog_search import (
    GroundImageryCatalogSearcher,
)
from disaster_monitor.application.ground_imagery.models import (
    GroundImageryRequest,
    GroundImageryRequestState,
)
from disaster_monitor.application.ground_imagery.request_indexes import (
    GroundImageryRequestIndexes,
)
from disaster_monitor.application.ground_imagery.request_lifecycle import (
    GroundImageryRequestLifecycle,
)
from disaster_monitor.application.ground_imagery.resolve_region import (
    GroundImageryRegionResolver,
)
from disaster_monitor.application.ground_imagery.select_observations import (
    GroundImagerySelection,
    SelectionReason,
    SelectionResult,
    SensorSelection,
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
from disaster_monitor.application.ports.ground_imagery.jobs import (
    GroundImageryJob,
    GroundImageryJobQueue,
    GroundImageryJobStatus,
    preparation_job,
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
    Sensor,
    TemporalRole,
)


class GroundImageryService(GroundImageryRequestLifecycle):
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
        job_queue: GroundImageryJobQueue | None = None,
    ) -> None:
        self._catalog = catalog
        super().__init__(
            context_reader,
            region_resolver,
            GroundImageryCatalogSearcher(
                catalog, maximum_catalog_items=maximum_catalog_items
            ),
            store,
            GroundImageryRequestIndexes(),
            clock,
            enabled,
        )
        self._artifact_workflow = GroundImageryArtifactWorkflow(
            region_resolver,
            clock=clock,
            renderer=renderer,
            raster_validator=raster_validator,
            artifact_store=artifact_store,
            tile_renderer=tile_renderer,
        )
        self._job_queue = job_queue
        self._artifact_access = GroundImageryArtifactAccess(
            self._artifact_workflow, self._store, self._indexes, self._clock
        )

    async def jobs_for_request(self, request_id: str) -> tuple[GroundImageryJob, ...]:
        await self.get_request(request_id)
        if self._job_queue is None:
            return ()
        return await self._job_queue.jobs_for_request(request_id)

    async def cleanup_artifacts(
        self, *, retention_days: int, now: datetime | None = None
    ) -> tuple[str, ...]:
        return await self._artifact_access.cleanup_artifacts(
            retention_days=retention_days, now=now
        )

    async def select_observation(
        self,
        request_id: str,
        *,
        sensor: Sensor,
        role: str,
        observation_id: str,
    ) -> GroundImageryRequest:
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
        request = await self.get_request(request_id)
        temporal_role = TemporalRole(role)
        if request.selection is None:
            raise ValueError("This imagery request has no catalog selection.")
        if request.selected_observation(sensor, temporal_role) is None:
            raise ValueError("The requested imagery role has no selected observation.")
        if self._job_queue is not None:
            now = self._clock()
            job = preparation_job(
                request_id=request.request_id,
                request_version=request.request_version,
                sensor=sensor,
                role=temporal_role,
                overview=overview,
                output_kind=output_kind,
                now=now,
            )
            await self._job_queue.enqueue(job)
            queued = replace(
                request,
                state=GroundImageryRequestState.QUEUED,
                updated_at=now,
                reason_codes=_identifiers.unique_reasons(
                    (*request.reason_codes, "artifact_preparation_queued")
                ),
            )
            await self._store.save_request(queued)
            return queued
        return await self._prepare_selection_now(
            request,
            sensor=sensor,
            role=temporal_role,
            overview=overview,
            output_kind=output_kind,
        )

    @property
    def job_queue(self) -> GroundImageryJobQueue | None:
        return self._job_queue

    async def execute_preparation_job(
        self, job: GroundImageryJob
    ) -> GroundImageryRequest:
        request = await self.get_request(job.request_id)
        if request.request_version != job.request_version:
            raise ValueError("The Ground job targets an obsolete request version.")
        updated = await self._prepare_selection_now(
            request,
            sensor=job.sensor,
            role=job.role,
            overview=job.overview,
            output_kind=job.output_kind,
        )
        final_state = await self._preparation_state(updated)
        completed = replace(updated, state=final_state)
        await self._store.save_request(completed)
        return completed

    async def _preparation_state(
        self, request: GroundImageryRequest
    ) -> GroundImageryRequestState:
        if self._job_queue is None:
            return GroundImageryRequestState.READY
        jobs = tuple(
            job
            for job in await self._job_queue.jobs_for_request(request.request_id)
            if job.request_version == request.request_version
        )
        artifacts = {(item.sensor, item.role) for item in request.artifacts}
        missing_active = any(
            job.status
            in {
                GroundImageryJobStatus.QUEUED,
                GroundImageryJobStatus.RUNNING,
                GroundImageryJobStatus.RETRY_WAIT,
            }
            and (job.sensor, job.role) not in artifacts
            for job in jobs
        )
        if missing_active:
            return GroundImageryRequestState.QUEUED
        if any(job.status is GroundImageryJobStatus.FAILED for job in jobs):
            return (
                GroundImageryRequestState.PARTIAL
                if request.artifacts
                else GroundImageryRequestState.FAILED
            )
        return GroundImageryRequestState.READY

    async def _prepare_selection_now(
        self,
        request: GroundImageryRequest,
        *,
        sensor: Sensor,
        role: TemporalRole,
        overview: bool,
        output_kind: str | None,
    ) -> GroundImageryRequest:
        updated = await self._artifact_workflow.prepare(
            request,
            sensor=sensor,
            role=role.value,
            overview=overview,
            output_kind=output_kind,
        )
        await self._store.save_request(updated)
        return updated

    async def mark_preparation_failed(
        self, request_id: str, *, detail: str
    ) -> GroundImageryRequest:
        request = await self.get_request(request_id)
        if request.state in {
            GroundImageryRequestState.CANCELLED,
            GroundImageryRequestState.READY,
        }:
            return request
        failed = replace(
            request,
            state=GroundImageryRequestState.FAILED,
            updated_at=self._clock(),
            reason_codes=_identifiers.unique_reasons(
                (*request.reason_codes, "artifact_preparation_failed")
            ),
        )
        await self._store.save_request(failed)
        return failed

    async def read_artifact(
        self, artifact_id: str
    ) -> tuple[StoredArtifact, bytes] | None:
        return await self._artifact_access.read_artifact(artifact_id)

    async def render_tile(self, artifact_id: str, zoom: int, x: int, y: int) -> bytes:
        return await self._artifact_access.render_tile(artifact_id, zoom, x, y)

    def readiness(self) -> dict[str, object]:
        """Return actionable provider/artifact readiness without probing upstream."""
        if not self._enabled:
            return {"state": "disabled", "detail": "Ground imagery is disabled."}
        return self._artifact_access.readiness()

    async def manifest(self, request_id: str) -> dict[str, object]:
        return await self._artifact_access.manifest(request_id)

    async def manifest_for_selection(
        self, selection_id_value: str
    ) -> dict[str, object]:
        """Resolve a stable selection manifest without exposing provider credentials."""
        return await self._artifact_access.manifest_for_selection(selection_id_value)

    async def aclose(self) -> None:
        await self._catalog.aclose()
        await self._region_resolver.aclose()
        await self._artifact_access.aclose()
