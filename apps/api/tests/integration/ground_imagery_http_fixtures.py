"""Typed ports and real raster/persistence wiring for Ground HTTP checks."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds

from disaster_monitor.application.ground_imagery.request_limits import (
    GroundImageryRequestLimiter,
)
from disaster_monitor.application.ground_imagery.resolve_region import (
    GroundImageryRegionResolver,
)
from disaster_monitor.application.ground_imagery.service import GroundImageryService
from disaster_monitor.application.ground_imagery.temporal_policy import ImpactOnset
from disaster_monitor.application.ports.ground_imagery.catalog import (
    GroundImageryCatalogPage,
    GroundImageryCatalogQuery,
)
from disaster_monitor.application.ports.ground_imagery.incidents import (
    IncidentImageryContext,
)
from disaster_monitor.application.ports.ground_imagery.rendering import (
    RenderedRaster,
    RenderRequest,
)
from disaster_monitor.application.ports.ground_imagery.repository import (
    GroundImageryRequestStore,
)
from disaster_monitor.domain.disaster import Disaster
from disaster_monitor.domain.imagery.observations import (
    AcquisitionIdentity,
    CaptureInterval,
    Observation,
    ObservationQuality,
    ObservationReadiness,
    QualityState,
    Sensor,
)
from disaster_monitor.domain.imagery.regions import (
    AssociationStatus,
    RegionEvidence,
    RegionSource,
    RegionSourceKind,
    polygon_from_geojson,
)
from disaster_monitor.infrastructure.ground_imagery.artifact_store import (
    FilesystemImageryArtifactStore,
)
from disaster_monitor.infrastructure.ground_imagery.geometry import (
    GeodesicGeometryEngine,
)
from disaster_monitor.infrastructure.ground_imagery.memory_jobs import (
    InMemoryGroundImageryJobQueue,
)
from disaster_monitor.infrastructure.ground_imagery.memory_repository import (
    InMemoryGroundImageryRequestStore,
)
from disaster_monitor.infrastructure.ground_imagery.raster_artifacts import (
    RasterioCogValidator,
    RasterioStoredArtifactTileRenderer,
)

GEOMETRY = polygon_from_geojson(
    {
        "type": "Polygon",
        "coordinates": [[[10, 1], [11, 1], [11, 2], [10, 2], [10, 1]]],
    }
)


@dataclass
class FakeIncidentReader:
    context: IncidentImageryContext

    async def get_imagery_context(self, incident_id: str):
        return self.context if incident_id == self.context.incident_id else None


class FakeCatalog:
    def __init__(self, observations: tuple[Observation, ...]):
        self.observations = observations
        self.queries: list[GroundImageryCatalogQuery] = []

    async def search(
        self, query: GroundImageryCatalogQuery
    ) -> GroundImageryCatalogPage:
        self.queries.append(query)
        return GroundImageryCatalogPage(
            self.observations, None, len(self.observations), True
        )

    async def aclose(self) -> None:
        return None


class FakeRenderer:
    async def render(self, request: RenderRequest) -> RenderedRaster:
        grid = request.grid
        with MemoryFile() as memory:
            with memory.open(
                driver="GTiff",
                width=grid.width,
                height=grid.height,
                count=3,
                dtype="uint8",
                crs=grid.crs,
                transform=from_bounds(
                    grid.min_x,
                    grid.min_y,
                    grid.max_x,
                    grid.max_y,
                    grid.width,
                    grid.height,
                ),
            ) as dataset:
                dataset.write(np.full((3, grid.height, grid.width), 100, dtype="uint8"))
            content = memory.read()
        return RenderedRaster(
            content=content,
            media_type="image/tiff",
            source_product_ids=(request.observation.identity.product_id,),
        )

    async def aclose(self) -> None:
        return None


def _observation(sensor: Sensor, product_id: str) -> Observation:
    timestamp = datetime(2024, 5, 12, tzinfo=UTC)
    return Observation(
        observation_id=product_id,
        sensor=sensor,
        identity=AcquisitionIdentity(
            product_id=product_id,
            provider="fixture",
            acquisition_id=product_id,
        ),
        capture=CaptureInterval(timestamp, timestamp + timedelta(minutes=5)),
        footprint=GEOMETRY,
        readiness=ObservationReadiness.RENDERABLE,
        quality=ObservationQuality(
            covered_fraction=1,
            usable_fraction=0.9,
            obscured_fraction=0.1,
            uncertain_fraction=0,
            uncovered_fraction=0,
            component_usable_fractions=(("core", 0.9),),
            quality_state=QualityState.USEFUL,
            mask_definition="fixture-v1",
        ),
        mode="IW" if sensor is Sensor.SENTINEL_1 else None,
        relative_orbit=24 if sensor is Sensor.SENTINEL_1 else None,
        orbit_direction="descending" if sensor is Sensor.SENTINEL_1 else None,
        polarizations=("VV", "VH") if sensor is Sensor.SENTINEL_1 else (),
        recipe_version="gamma0-terrain-v1" if sensor is Sensor.SENTINEL_1 else None,
    )


def _service(
    artifact_root: Path | None = None,
    *,
    job_queue: InMemoryGroundImageryJobQueue | None = None,
    rate_limiter: GroundImageryRequestLimiter | None = None,
    catalog: FakeCatalog | None = None,
    clock=None,
    renderer=None,
    store: GroundImageryRequestStore | None = None,
) -> GroundImageryService:
    source = RegionSource(
        source_id="fixture:impact",
        source_kind=RegionSourceKind.MAPPED_IMPACT,
        publisher="Fixture",
        reference="https://example.test/impact",
    )
    context = IncidentImageryContext(
        incident_id="incident-1",
        disaster=Disaster.FLOOD,
        country_code="BRA",
        event_time=datetime(2024, 5, 5, tzinfo=UTC),
        onset=ImpactOnset.exact(
            datetime(2024, 5, 5, tzinfo=UTC), source_id="fixture:event"
        ),
        evidence=(
            RegionEvidence(
                evidence_id="impact",
                geometry=GEOMETRY,
                source=source,
                association=AssociationStatus.CONFIRMED,
                semantic_role="mapped impact",
            ),
        ),
    )
    artifact_store = (
        None if artifact_root is None else FilesystemImageryArtifactStore(artifact_root)
    )
    return GroundImageryService(
        FakeIncidentReader(context),
        GroundImageryRegionResolver(GeodesicGeometryEngine()),
        catalog
        or FakeCatalog(
            (
                _observation(Sensor.SENTINEL_1, "s1-1"),
                _observation(Sensor.SENTINEL_2, "s2-1"),
            )
        ),
        store if store is not None else InMemoryGroundImageryRequestStore(),
        clock=clock or (lambda: datetime(2024, 5, 20, tzinfo=UTC)),
        renderer=renderer or (None if artifact_store is None else FakeRenderer()),
        raster_validator=None if artifact_store is None else RasterioCogValidator(),
        artifact_store=artifact_store,
        tile_renderer=(
            None
            if artifact_store is None
            else RasterioStoredArtifactTileRenderer(artifact_store)
        ),
        job_queue=job_queue,
        rate_limiter=rate_limiter,
    )
