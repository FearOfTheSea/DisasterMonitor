"""Controlled external ports for desktop/capacity checks. Never live evidence."""

import asyncio
import struct
import zlib
from collections.abc import AsyncIterator
from dataclasses import replace
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
from disaster_monitor.application.incidents.active_incidents import (
    ActiveIncidentsService,
)
from disaster_monitor.application.incidents.discovery_scan import DiscoveryScanService
from disaster_monitor.application.incidents.imagery_context import (
    ActiveIncidentImageryContextReader,
)
from disaster_monitor.application.media import (
    DisasterMediaCandidate,
    MediaCreditKind,
    MediaEventContext,
    MediaRightsStatus,
    RetrievedMedia,
)
from disaster_monitor.application.media_analysis.event_media import DisasterMediaService
from disaster_monitor.application.ports.discovery import DiscoveryStore
from disaster_monitor.application.ports.ground_imagery.catalog import (
    CatalogSearchError,
    GroundImageryCatalogPage,
    GroundImageryCatalogQuery,
)
from disaster_monitor.application.ports.ground_imagery.rendering import (
    RenderedRaster,
    RenderRequest,
)
from disaster_monitor.domain.disaster_types import Disaster
from disaster_monitor.domain.discovery import (
    DiscoveryArticle,
    DiscoveryBatch,
    ReportingInterval,
)
from disaster_monitor.domain.events import (
    EventCoordinate,
    EventGeometry,
    EventGeometryKind,
)
from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.domain.imagery.observations import (
    AcquisitionIdentity,
    CaptureInterval,
    Observation,
    ObservationReadiness,
    Sensor,
)
from disaster_monitor.infrastructure.ground_imagery.artifact_store import (
    FilesystemImageryArtifactStore,
)
from disaster_monitor.infrastructure.ground_imagery.geometry import (
    GeodesicGeometryEngine,
)
from disaster_monitor.infrastructure.ground_imagery.memory_repository import (
    InMemoryGroundImageryRequestStore,
)
from disaster_monitor.infrastructure.ground_imagery.raster_artifacts import (
    RasterioCogValidator,
    RasterioStoredArtifactTileRenderer,
)
from disaster_monitor.infrastructure.media.memory_store import InMemoryMediaAssetStore

NOW = datetime(2026, 10, 18, tzinfo=UTC)


class InspectionFeed:
    source_id = "CONTROLLED-inspection-feed"

    async def discover(
        self, *, interval: ReportingInterval
    ) -> AsyncIterator[DiscoveryBatch]:
        await asyncio.sleep(1)
        if interval.days == 1:
            yield DiscoveryBatch(successful_operations=1)
            return
        if interval.days == 3:
            yield DiscoveryBatch(
                failed_operations=1, issues=("CONTROLLED provider failure.",)
            )
            return
        articles = []
        for index, hazard in enumerate(Disaster):
            title = f"CONTROLLED {hazard.value.replace('_', ' ')} at Region {index}"
            source = SourceReference(
                "controlled-news",
                "CONTROLLED International News",
                title,
                f"https://controlled.example/{hazard.value}/0",
                NOW,
                None,
                NOW,
            )
            point = EventCoordinate(10, 100 + 5 * index)
            geometry = EventGeometry(
                EventGeometryKind.POINT, coordinates=(point,), source=source
            )
            if hazard is Disaster.DROUGHT:
                geometry = EventGeometry(
                    EventGeometryKind.AREA,
                    coordinates=tuple(
                        EventCoordinate(lat, lon)
                        for lat, lon in (
                            (10, 120),
                            (10, 120.1),
                            (10.1, 120.1),
                            (10.1, 120),
                            (10, 120),
                        )
                    ),
                    source=source,
                    description=(
                        "Source-reported administrative context; "
                        "not a damage perimeter."
                    ),
                )
            for report in range(8):
                articles.append(
                    DiscoveryArticle(
                        replace(
                            source,
                            canonical_url=f"https://controlled.example/{hazard.value}/{report}",
                            title=f"{title} — article {report}",
                            published_at=None
                            if report == 7
                            else NOW - timedelta(hours=report),
                            updated_at=NOW if report == 1 else None,
                        ),
                        (
                            "Correction: no deaths were reported "
                            "in North District on Tuesday. "
                            if report == 1
                            else (
                                f"Preliminary reports said {10 + report} people died "
                                f"across Region {index} on Monday. "
                            )
                        )
                        + "Four people were injured. 200 people were displaced, "
                        "including 50 in North District. "
                        + "Roads and bridges were damaged. "
                        "Water systems were disrupted. "
                        + "Electricity networks were damaged. "
                        "Communications networks are down. "
                        + "Schools were destroyed. Property losses reached $5 million.",
                        indexed_at=NOW,
                        event_time=NOW - timedelta(days=2),
                        location=f"Region {index}",
                        geometry=geometry,
                        event_key=f"controlled:{hazard.value}",
                        origin="https://controlled.example/wire",
                    )
                )
        articles.append(
            DiscoveryArticle(
                SourceReference(
                    "controlled-news",
                    "CONTROLLED News",
                    "CONTROLLED drought in Unresolved Valley",
                    "https://controlled.example/unlocated",
                    NOW,
                    None,
                    NOW,
                ),
                "Displacement remains unknown.",
                location="Unresolved Valley",
            )
        )
        yield DiscoveryBatch(
            tuple(articles),
            successful_operations=7,
            failed_operations=1 if interval.days == 14 else 0,
            truncated=interval.days == 30,
            issues=("CONTROLLED collection limits and access notice.",),
        )


class InspectionMediaProvider:
    provider_id = "CONTROLLED-synthetic-images"

    async def discover(
        self, context: MediaEventContext, *, now: datetime
    ) -> tuple[DisasterMediaCandidate, ...]:
        del now
        if not context.collected_articles:
            return ()
        source = context.collected_articles[0]
        candidates = []
        for index in range(9):
            candidates.append(
                DisasterMediaCandidate(
                    f"controlled-image:{index}",
                    self.provider_id,
                    source.source_id,
                    source.publisher,
                    source.canonical_url,
                    f"https://controlled.example/images/{index}.png",
                    source.title,
                    source.title,
                    f"CONTROLLED SYNTHETIC TEST IMAGE {index}; "
                    "not a disaster photograph.",
                    "CONTROLLED fixture generator",
                    MediaCreditKind.PUBLISHER,
                    source.published_at,
                    None,
                    None,
                    None,
                    MediaRightsStatus.SOURCE_PREVIEW,
                    index,
                )
            )
        return tuple(candidates)

    async def retrieve(self, candidate: DisasterMediaCandidate) -> RetrievedMedia:
        index = int(candidate.candidate_id.rsplit(":", 1)[-1])
        await asyncio.sleep(0.01)
        if index == 8:
            raise OSError("CONTROLLED broken image")
        if index == 7:
            index = 0
        content = _synthetic_png(index)
        return RetrievedMedia(candidate, content, "image/png", 640, 360)


class InspectionCatalog:
    def __init__(self, metrics: dict[str, int]) -> None:
        self._metrics = metrics

    async def search(
        self, query: GroundImageryCatalogQuery
    ) -> GroundImageryCatalogPage:
        self._metrics["catalog_provider_calls"] += 1
        await asyncio.sleep(0.02)
        west = query.geometry.bounds[0]
        if 109 < west < 111:
            raise CatalogSearchError(
                "CONTROLLED provider failure",
                reason_code="provider_error",
                retryable=False,
            )
        if 99 < west < 101:
            return GroundImageryCatalogPage((), None, 0, True)
        capture = query.start + (query.end - query.start) / 2
        identifier = f"CONTROLLED-{query.sensor.value}-{capture.isoformat()}"
        observation = Observation(
            identifier,
            query.sensor,
            AcquisitionIdentity(
                identifier,
                "CONTROLLED provider",
                acquisition_id=identifier,
                platform="CONTROLLED sensor",
                source_url="https://controlled.example/catalog",
            ),
            CaptureInterval(capture, capture),
            query.geometry,
            ObservationReadiness.RENDERABLE,
        )
        return GroundImageryCatalogPage((observation,), None, 1, True)

    async def aclose(self) -> None:
        pass


class InspectionRenderer:
    def __init__(self, metrics: dict[str, int]) -> None:
        self._metrics = metrics

    async def render(self, request: RenderRequest) -> RenderedRaster:
        self._metrics["render_provider_calls"] += 1
        grid = request.grid
        await asyncio.sleep(0.02)
        radar = request.observation.sensor is Sensor.SENTINEL_1
        bands = (
            ("VV", "VH", "dataMask")
            if radar
            else ("B04", "B03", "B02", "SCL", "dataMask")
        )
        values = np.ones((len(bands), grid.height, grid.width), dtype="float32")
        if radar:
            values[0] = np.linspace(0.02, 0.2, grid.width)[None, :]
            values[1] = 0.04
        else:
            values[:3] = np.array([0.2, 0.3, 0.1])[:, None, None]
            values[3] = 4
        with MemoryFile() as memory:
            with memory.open(
                driver="GTiff",
                width=grid.width,
                height=grid.height,
                count=len(bands),
                dtype="float32",
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
                dataset.write(values)
                dataset.descriptions = bands
            return RenderedRaster(
                memory.read(),
                "image/tiff",
                (request.observation.identity.product_id,),
                (
                    ("sensor", request.observation.sensor.value),
                    ("band_order", ",".join(bands)),
                ),
            )

    async def aclose(self) -> None:
        pass


def inspection_discovery(store: DiscoveryStore) -> DiscoveryScanService:
    return DiscoveryScanService((InspectionFeed(),), store, clock=lambda: NOW)


def inspection_media(store: InMemoryMediaAssetStore) -> DisasterMediaService:
    return DisasterMediaService((InspectionMediaProvider(),), store, clock=lambda: NOW)


def inspection_ground(
    incidents: ActiveIncidentsService,
    root: Path,
    *,
    rate_limited: bool = True,
    metrics: dict[str, int] | None = None,
) -> GroundImageryService:
    metrics = (
        metrics
        if metrics is not None
        else {"catalog_provider_calls": 0, "render_provider_calls": 0}
    )
    artifacts = FilesystemImageryArtifactStore(root)
    return GroundImageryService(
        ActiveIncidentImageryContextReader(incidents),
        GroundImageryRegionResolver(GeodesicGeometryEngine()),
        InspectionCatalog(metrics),
        InMemoryGroundImageryRequestStore(),
        clock=lambda: NOW,
        renderer=InspectionRenderer(metrics),
        raster_validator=RasterioCogValidator(),
        artifact_store=artifacts,
        tile_renderer=RasterioStoredArtifactTileRenderer(artifacts),
        monitoring_available=False,
        rate_limiter=GroundImageryRequestLimiter() if rate_limited else None,
    )


def _synthetic_png(index: int) -> bytes:
    def chunk(kind: bytes, content: bytes) -> bytes:
        payload = kind + content
        return (
            struct.pack(">I", len(content))
            + payload
            + struct.pack(">I", zlib.crc32(payload))
        )

    rows = b"".join(b"\0" + bytes((25, 55 + index * 10, 75)) * 640 for _ in range(360))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">2I5B", 640, 360, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )
