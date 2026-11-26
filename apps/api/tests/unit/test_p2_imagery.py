from datetime import UTC, datetime

import httpx
import numpy as np
import pytest
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds

from disaster_monitor.application.ground_imagery.impact_regions import (
    CemsDeliveredProduct,
    CemsProductKind,
    cems_product_region,
    shakemap_source_regions,
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
from disaster_monitor.domain.imagery.observations import (
    AcquisitionIdentity,
    CaptureInterval,
    Observation,
    ObservationReadiness,
    Sensor,
)
from disaster_monitor.domain.imagery.regions import (
    RegionSourceKind,
    polygon_from_geojson,
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("primary_code", "primary_retryable", "fallback_code", "fallback_retryable"),
    [
        ("processing_timeout", True, "public_cog_unavailable", False),
        ("credentials_required", False, "public_cog_unavailable", False),
        ("permission_denied", False, "public_cog_download_failed", True),
        ("quota_deferred", True, "public_cog_invalid", False),
    ],
)
async def test_failed_imagery_paths_preserve_remote_cause_and_local_diagnostic(
    primary_code: str,
    primary_retryable: bool,
    fallback_code: str,
    fallback_retryable: bool,
) -> None:
    primary_error = GroundImageryRenderError(
        "Remote processing did not deliver the selected observation.",
        reason_code=primary_code,
        retryable=primary_retryable,
    )
    fallback_error = GroundImageryRenderError(
        "The public asset could not deliver a local alternative.",
        reason_code=fallback_code,
        retryable=fallback_retryable,
    )

    class FailedRenderer:
        def __init__(self, error: GroundImageryRenderError):
            self.error = error

        async def render(self, request: RenderRequest):
            raise self.error

        async def aclose(self) -> None:
            return None

    renderer = FallbackGroundImageryRenderer(
        FailedRenderer(primary_error), FailedRenderer(fallback_error)
    )
    with pytest.raises(GroundImageryRenderError) as caught:
        await renderer.render(_render_request())

    assert caught.value.reason_code == primary_code
    assert caught.value.retryable is (primary_retryable or fallback_retryable)
    assert primary_code in str(caught.value)
    assert fallback_code in str(caught.value)
    assert str(primary_error) in str(caught.value)
    assert str(fallback_error) in str(caught.value)
    assert caught.value.__cause__ is fallback_error


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reason_code",
    [
        "processing_request_invalid",
        "unverified_product_identity",
        "unexpected_content_type",
    ],
)
async def test_imagery_identity_and_request_failures_do_not_try_local_fallback(
    reason_code: str,
) -> None:
    original = GroundImageryRenderError(
        "The selected acquisition cannot be verified.",
        reason_code=reason_code,
        retryable=False,
    )

    class InvalidRemote:
        async def render(self, request: RenderRequest):
            raise original

        async def aclose(self) -> None:
            return None

    class UnexpectedFallback:
        async def render(self, request: RenderRequest):
            raise AssertionError("A rejected identity must not use a fallback.")

        async def aclose(self) -> None:
            return None

    with pytest.raises(GroundImageryRenderError) as caught:
        await FallbackGroundImageryRenderer(
            InvalidRemote(), UnexpectedFallback()
        ).render(_render_request())
    assert caught.value is original
