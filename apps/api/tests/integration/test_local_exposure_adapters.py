import json
from datetime import UTC, datetime

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from disaster_monitor.domain.exposure import (
    ExposureDataset,
    ExposureDatasetRole,
    ExposureGeometry,
    ExposureGeometryRole,
    InfrastructureCategory,
)
from disaster_monitor.domain.imagery.regions import polygon_from_geojson
from disaster_monitor.infrastructure.exposure.local_osm import LocalOsmAssetExposure
from disaster_monitor.infrastructure.exposure.population_raster import (
    PopulationRasterExposure,
)

NOW = datetime(2026, 9, 14, tzinfo=UTC)


@pytest.mark.asyncio
async def test_population_raster_sums_only_source_geometry_pixels(tmp_path) -> None:
    raster_path = tmp_path / "worldpop.tif"
    with rasterio.open(
        raster_path,
        "w",
        driver="GTiff",
        height=2,
        width=2,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_origin(0, 2, 1, 1),
        nodata=-9999,
    ) as target:
        target.write(np.array([[10, 20], [30, 40]], dtype="float32"), 1)
    geometry = ExposureGeometry(
        polygon_from_geojson(
            {
                "type": "Polygon",
                "coordinates": [[[0, 0], [1, 0], [1, 2], [0, 2], [0, 0]]],
            }
        ),
        ExposureGeometryRole.MAPPED_HAZARD,
        "fixture-footprint",
        "v1",
        NOW,
    )
    provider = PopulationRasterExposure(
        raster_path,
        ExposureDataset(
            dataset_id="worldpop-global2-2025-1km",
            publisher="WorldPop",
            version="global2-2025",
            vintage=2025,
            resolution_m=1000,
            license_name="WorldPop data license",
            source_url="https://www.worldpop.org/",
            role=ExposureDatasetRole.PRIMARY,
            uncertainty="Modelled gridded population; pixel allocation is uncertain.",
        ),
        clock=lambda: NOW,
    )

    estimate = await provider.estimate(geometry)

    assert estimate.population == pytest.approx(40)
    assert estimate.dataset.vintage == 2025
    assert estimate.geometry_hash == geometry.geometry.sha256()


@pytest.mark.asyncio
async def test_local_osm_extract_filters_supported_assets_and_intersects_geometry(
    tmp_path,
) -> None:
    extract = tmp_path / "assets.geojson"
    extract.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "id": "node/1",
                        "geometry": {"type": "Point", "coordinates": [0.5, 0.5]},
                        "properties": {
                            "amenity": "hospital",
                            "name": "Inside hospital",
                        },
                    },
                    {
                        "type": "Feature",
                        "id": "node/2",
                        "geometry": {"type": "Point", "coordinates": [5, 5]},
                        "properties": {"amenity": "school", "name": "Outside school"},
                    },
                    {
                        "type": "Feature",
                        "id": "node/3",
                        "geometry": {"type": "Point", "coordinates": [0.4, 0.4]},
                        "properties": {"shop": "bakery", "name": "Unsupported"},
                    },
                ],
            }
        )
    )
    geometry = ExposureGeometry(
        polygon_from_geojson(
            {
                "type": "Polygon",
                "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
            }
        ),
        ExposureGeometryRole.MAPPED_HAZARD,
        "source",
        "v1",
        NOW,
    )

    assets = await LocalOsmAssetExposure(
        extract,
        extract_version="geofabrik-2026-09-01",
    ).intersecting_assets(geometry)

    assert [(item.asset_id, item.category) for item in assets] == [
        ("node/1", InfrastructureCategory.HOSPITAL)
    ]
