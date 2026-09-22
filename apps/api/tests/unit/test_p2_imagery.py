from datetime import UTC, datetime
from pathlib import Path

import httpx
import numpy as np
import pytest
from affine import Affine
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds

from disaster_monitor.application.ground_imagery.impact_regions import (
    CemsDeliveredProduct,
    CemsProductKind,
    cems_product_region,
    shakemap_source_regions,
)
from disaster_monitor.application.ground_imagery.offline_packages import (
    OfflineTile,
    build_local_basemap_package,
    build_mbtiles_package,
)
from disaster_monitor.application.ports.ground_imagery.rendering import (
    GroundImageryRenderError,
    ImageryGrid,
    RenderRequest,
)
from disaster_monitor.domain.earthquake_context import (
    ProductBounds,
    ProductReference,
    ShakeMapLayer,
    ShakeMeasure,
)
from disaster_monitor.domain.imagery.analysis import (
    AnalyticalFindingReview,
    FindingReviewDecision,
)
from disaster_monitor.domain.imagery.observations import (
    AcquisitionIdentity,
    CaptureInterval,
    Observation,
    ObservationReadiness,
    Sensor,
)
from disaster_monitor.domain.imagery.regions import RegionSourceKind
from disaster_monitor.infrastructure.ground_imagery.analytics import (
    BurnChangeAlgorithm,
    FloodChangeAlgorithm,
)
from disaster_monitor.infrastructure.ground_imagery.geometry_partitioning import (
    GeometryPartitionKind,
    partition_geometry,
)
from disaster_monitor.infrastructure.ground_imagery.gfm_regions import (
    GfmMaskLineage,
    extract_gfm_components,
)
from disaster_monitor.infrastructure.ground_imagery.local_products import (
    FallbackGroundImageryRenderer,
    PublicCogRenderer,
)
from disaster_monitor.infrastructure.ground_imagery.raster_quality import (
    RasterQualityRequirements,
    assess_raster_quality,
)

NOW = datetime(2026, 9, 15, 8, tzinfo=UTC)


def test_gfm_mask_components_are_bounded_and_retain_processing_lineage() -> None:
    mask = np.zeros((6, 8), dtype=np.uint8)
    mask[1:3, 1:3] = 1
    mask[3:6, 5:8] = 1
    lineage = GfmMaskLineage(
        source_item_id="GFM_20260915T060000Z",
        source_asset_url="https://example.test/gfm.tif",
        source_sha256="a" * 64,
        source_crs="EPSG:4326",
        mask_band="ensemble_flood_extent",
        threshold_expression="pixel == 1",
        algorithm_version="gfm-components:v1",
        captured_at=NOW,
        retrieved_at=NOW,
    )

    regions = extract_gfm_components(
        mask,
        transform=Affine.translation(100, 20) @ Affine.scale(0.1, -0.1),
        lineage=lineage,
        minimum_pixels=3,
        maximum_components=10,
    )

    assert [region.pixel_count for region in regions] == [9, 4]
    assert all(
        region.evidence.source.source_kind is RegionSourceKind.OBSERVATION_MASK
        for region in regions
    )
    assert regions[0].evidence.derivation_inputs == (
        "GFM_20260915T060000Z",
        "a" * 64,
        "pixel == 1",
        "gfm-components:v1",
    )
    assert regions[0].evidence.semantic_role == "official observed flood extent"


def test_gfm_lineage_rejects_non_sha256_checksum_text() -> None:
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        GfmMaskLineage(
            source_item_id="GFM_20260915T060000Z",
            source_asset_url="https://example.test/gfm.tif",
            source_sha256="z" * 64,
            source_crs="EPSG:4326",
            mask_band="ensemble_flood_extent",
            threshold_expression="pixel == 1",
            algorithm_version="gfm-components:v1",
            captured_at=NOW,
            retrieved_at=NOW,
        )


def test_cems_and_shakemap_products_become_distinct_source_regions() -> None:
    polygon = {
        "type": "Polygon",
        "coordinates": [[[10, 45], [11, 45], [11, 46], [10, 46], [10, 45]]],
    }
    product = CemsDeliveredProduct(
        activation_code="EMSR999",
        product_id="EMSR999_AOI01_DEL_MONIT01_v2",
        version="2",
        kind=CemsProductKind.DELINEATION,
        geometry=polygon,
        source_url="https://mapping.emergency.copernicus.eu/EMSR999/product.zip",
        published_at=NOW,
    )

    cems = cems_product_region(product)
    assert cems.source.source_kind is RegionSourceKind.MAPPED_IMPACT
    assert cems.semantic_role == "CEMS delivered delineation"
    assert ("activation", "EMSR999") in cems.source.metadata
    assert ("product_version", "2") in cems.source.metadata

    layer = ShakeMapLayer(
        product=ProductReference(
            "us7000test-shakemap", "shakemap", "4", "UPDATE", NOW, "us7000test"
        ),
        measure=ShakeMeasure.MMI,
        unit="intensity",
        coverage_url="https://earthquake.usgs.gov/product/shakemap/grid.xml",
        coverage_sha256="b" * 64,
        bounds=ProductBounds(34, -119, 36, -117),
        maximum=8.1,
    )
    shaking = shakemap_source_regions((layer,))

    assert len(shaking) == 1
    assert shaking[0].source.source_kind is RegionSourceKind.MODELED_HAZARD
    assert shaking[0].semantic_role == "USGS ShakeMap shaking coverage"
    assert shaking[0].association.value == "confirmed"


def test_partitioning_handles_antimeridian_polar_and_multiple_utm_zones() -> None:
    antimeridian = _polygon([[179, 10], [-179, 10], [-179, 12], [179, 12], [179, 10]])
    polar = _polygon([[10, 85], [20, 85], [20, 86], [10, 86], [10, 85]])
    multi_zone = _polygon([[-1, 50], [8, 50], [8, 51], [-1, 51], [-1, 50]])

    anti_plan = partition_geometry(antimeridian)
    polar_plan = partition_geometry(polar)
    zone_plan = partition_geometry(multi_zone)

    assert anti_plan.kind is GeometryPartitionKind.ANTIMERIDIAN
    assert len(anti_plan.parts) == 2
    assert polar_plan.kind is GeometryPartitionKind.POLAR
    assert {part.grid_crs for part in polar_plan.parts} == {"EPSG:32661"}
    assert zone_plan.kind is GeometryPartitionKind.MULTI_UTM_ZONE
    assert len({part.grid_crs for part in zone_plan.parts}) >= 2
    assert all(part.merge_order >= 0 for part in zone_plan.parts)


def test_radar_and_optical_change_are_analytical_and_quality_gated() -> None:
    before_vv = np.array([[0.4, 0.5], [0.3, 0.7]], dtype=np.float32)
    after_vv = np.array([[0.05, 0.5], [0.04, 0.68]], dtype=np.float32)
    flood = FloodChangeAlgorithm().measure(
        before_vv,
        after_vv,
        valid_mask=np.ones((2, 2), dtype=bool),
        source_product_ids=("S1-before", "S1-after"),
    )
    assert flood.algorithm_id == "sentinel-1-flood-change"
    assert flood.algorithm_version == "1.0.0"
    assert flood.evidence_role == "analytical_observation"
    assert flood.metrics["changed_fraction"] == pytest.approx(0.5)
    assert flood.authoritative_extent is False

    before_nir = np.array([[0.8, 0.7]], dtype=np.float32)
    before_swir = np.array([[0.2, 0.3]], dtype=np.float32)
    after_nir = np.array([[0.3, 0.7]], dtype=np.float32)
    after_swir = np.array([[0.6, 0.3]], dtype=np.float32)
    burn = BurnChangeAlgorithm().measure(
        before_nir,
        before_swir,
        after_nir,
        after_swir,
        valid_mask=np.ones((1, 2), dtype=bool),
        cloud_fraction=0.1,
        source_product_ids=("S2-before", "S2-after"),
    )
    assert burn.metrics["changed_fraction"] == pytest.approx(0.5)
    assert burn.interpretation.startswith("Analytical Sentinel-2")

    with pytest.raises(ValueError, match="cloud gate"):
        BurnChangeAlgorithm().measure(
            before_nir,
            before_swir,
            after_nir,
            after_swir,
            valid_mask=np.ones((1, 2), dtype=bool),
            cloud_fraction=0.8,
            source_product_ids=("S2-before", "S2-after"),
        )


def test_human_review_wraps_but_does_not_mutate_analytical_output() -> None:
    finding = FloodChangeAlgorithm().measure(
        np.array([[0.4]], dtype=np.float32),
        np.array([[0.05]], dtype=np.float32),
        valid_mask=np.ones((1, 1), dtype=bool),
        source_product_ids=("before", "after"),
    )
    review = AnalyticalFindingReview.create(
        finding=finding,
        decision=FindingReviewDecision.ACCEPTED,
        reviewer_id="operator:alice",
        reviewed_at=NOW,
        annotation="Consistent with the official extent; still analytical.",
    )

    assert review.finding_id == finding.finding_id
    assert review.finding_sha256 == finding.sha256
    assert review.decision is FindingReviewDecision.ACCEPTED
    assert review.review_id.startswith("imagery-review:")


def test_mbtiles_package_requires_redistribution_permission(tmp_path: Path) -> None:
    destination = tmp_path / "incident.mbtiles"
    tile = OfflineTile(zoom=3, x=4, y=2, content=b"tile")

    manifest = build_mbtiles_package(
        destination,
        tiles=(tile,),
        package_id="offline:test",
        name="Incident test package",
        attribution="Open test data",
        source_license="CC-BY-4.0",
        redistribution_permitted=True,
        bounds=(-10, -5, 10, 5),
    )

    assert destination.is_file()
    assert manifest.tile_count == 1
    assert manifest.sha256
    basemap = build_local_basemap_package(
        tmp_path / "basemap.mbtiles",
        tiles=(OfflineTile(0, 0, 0, b"png"),),
        package_id="basemap:test",
        name="Local basemap",
        attribution="© OpenStreetMap contributors",
        source_license="ODbL-1.0",
        redistribution_permitted=True,
        bounds=(-180, -85, 180, 85),
    )
    assert basemap.format == "mbtiles-1.3"
    with pytest.raises(ValueError, match="redistribution"):
        build_mbtiles_package(
            tmp_path / "forbidden.mbtiles",
            tiles=(tile,),
            package_id="offline:forbidden",
            name="Forbidden",
            attribution="Restricted",
            source_license="restricted",
            redistribution_permitted=False,
            bounds=(-10, -5, 10, 5),
        )


@pytest.mark.asyncio
async def test_public_cog_renderer_is_a_bounded_local_processing_fallback() -> None:
    source = _source_geotiff()
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, content=source, headers={"content-type": "image/tiff"}
            )
        )
    )
    request = RenderRequest(
        observation=_observation(),
        region=_polygon([[10, 45], [11, 45], [11, 46], [10, 46], [10, 45]]),
        grid=ImageryGrid("EPSG:4326", 10, 45, 11, 46, 0.1, 10, 10, "test"),
        recipe_version="direct-cog:v1",
        output_kind="analysis",
    )

    rendered = await PublicCogRenderer(
        allowed_hosts=frozenset({"data.example.test"}), client=client
    ).render(request)
    await client.aclose()

    assert rendered.source_product_ids == ("S1-test",)
    assert ("processing_path", "direct_public_cog_local") in rendered.provider_metadata
    with MemoryFile(rendered.content) as memory:
        with memory.open() as dataset:
            assert dataset.crs.to_string() == "EPSG:4326"
            assert dataset.bounds.left == pytest.approx(10)


@pytest.mark.asyncio
async def test_fallback_uses_local_cog_only_for_an_expected_remote_failure() -> None:
    class UnavailableRemote:
        async def render(self, request: RenderRequest):
            raise GroundImageryRenderError(
                "credentials missing",
                reason_code="credentials_required",
                retryable=False,
            )

        async def aclose(self) -> None:
            return None

    class Local:
        async def render(self, request: RenderRequest):
            return "local-result"

        async def aclose(self) -> None:
            return None

    assert (
        await FallbackGroundImageryRenderer(UnavailableRemote(), Local()).render(
            _render_request()
        )
        == "local-result"
    )


def test_raster_quality_checks_band_order_masks_noise_and_scl_semantics() -> None:
    values = np.zeros((3, 4, 4), dtype=np.float32)
    values[0] = 0.005
    values[1] = 0.2
    values[2] = 1
    values[2, 0, 0] = 0
    with MemoryFile() as memory:
        with memory.open(
            driver="GTiff",
            width=4,
            height=4,
            count=3,
            dtype="float32",
            crs="EPSG:4326",
            transform=from_bounds(10, 45, 11, 46, 4, 4),
            nodata=-9999,
        ) as dataset:
            dataset.descriptions = ("VV", "VH", "dataMask")
            dataset.write(values)
            report = assess_raster_quality(
                dataset,
                RasterQualityRequirements(
                    expected_band_order=("VV", "VH", "dataMask"),
                    data_mask_band=3,
                    radar_bands=(1, 2),
                    radar_noise_floor=0.01,
                    maximum_sub_noise_fraction=0.6,
                ),
            )
    assert report.usable_fraction == pytest.approx(15 / 16)
    assert report.sub_noise_fraction == pytest.approx(0.5)

    values[2, 0, 0] = 99
    with MemoryFile() as memory:
        with memory.open(
            driver="GTiff",
            width=4,
            height=4,
            count=3,
            dtype="float32",
            crs="EPSG:4326",
            transform=from_bounds(10, 45, 11, 46, 4, 4),
        ) as dataset:
            dataset.descriptions = ("B04", "B08", "SCL")
            dataset.write(values)
            with pytest.raises(ValueError, match="SCL"):
                assess_raster_quality(
                    dataset,
                    RasterQualityRequirements(
                        expected_band_order=("B04", "B08", "SCL"), scl_band=3
                    ),
                )


def _polygon(coordinates: list[list[float]]):
    from disaster_monitor.domain.imagery.regions import polygon_from_geojson

    return polygon_from_geojson({"type": "Polygon", "coordinates": [coordinates]})


def _observation() -> Observation:
    return Observation(
        observation_id="observation:S1-test",
        sensor=Sensor.SENTINEL_1,
        identity=AcquisitionIdentity("S1-test", "CDSE"),
        capture=CaptureInterval(NOW, NOW),
        footprint=_polygon([[10, 45], [11, 45], [11, 46], [10, 46], [10, 45]]),
        readiness=ObservationReadiness.RENDERABLE,
        assets=(("cog", "https://data.example.test/S1-test.tif"),),
    )


def _render_request() -> RenderRequest:
    return RenderRequest(
        observation=_observation(),
        region=_observation().footprint,
        grid=ImageryGrid("EPSG:4326", 10, 45, 11, 46, 0.1, 10, 10, "test"),
        recipe_version="direct-cog:v1",
        output_kind="analysis",
    )


def _source_geotiff() -> bytes:
    with MemoryFile() as memory:
        with memory.open(
            driver="GTiff",
            width=10,
            height=10,
            count=1,
            dtype="float32",
            crs="EPSG:4326",
            transform=from_bounds(10, 45, 11, 46, 10, 10),
        ) as dataset:
            dataset.write(np.ones((1, 10, 10), dtype=np.float32))
        return memory.read()
