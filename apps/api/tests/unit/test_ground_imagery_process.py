import io
import json
import tarfile
from datetime import UTC, datetime

import httpx
import pytest

from disaster_monitor.application.ground_imagery.artifact_workflow import (
    GroundImageryArtifactWorkflow,
)
from disaster_monitor.application.ground_imagery.resolve_region import (
    GroundImageryRegionResolver,
)
from disaster_monitor.application.ports.ground_imagery.rendering import (
    ImageryGrid,
    RenderRequest,
)
from disaster_monitor.domain.imagery.observations import (
    AcquisitionIdentity,
    CaptureInterval,
    Observation,
    ObservationReadiness,
    Sensor,
)
from disaster_monitor.domain.imagery.regions import polygon_from_geojson
from disaster_monitor.infrastructure.ground_imagery.geometry import (
    GeodesicGeometryEngine,
)
from disaster_monitor.infrastructure.ground_imagery.sentinel_hub import (
    ProcessRenderingError,
    _verified_response_raster,
    build_process_request,
)


def _request(sensor: Sensor = Sensor.SENTINEL_2) -> RenderRequest:
    region = polygon_from_geojson(
        {
            "type": "Polygon",
            "coordinates": [[[10, 1], [11, 1], [11, 2], [10, 2], [10, 1]]],
        }
    )
    observation = Observation(
        observation_id="observation:1",
        sensor=sensor,
        identity=AcquisitionIdentity(product_id="SELECTED_PRODUCT", provider="cdse"),
        capture=CaptureInterval(
            datetime(2026, 9, 24, 3, 25, tzinfo=UTC),
            datetime(2026, 9, 24, 3, 26, tzinfo=UTC),
        ),
        footprint=region,
        readiness=ObservationReadiness.RENDERABLE,
    )
    return RenderRequest(
        observation=observation,
        region=region,
        grid=ImageryGrid("EPSG:32632", 0, 0, 100, 100, 10, 10, 10, "overview"),
        recipe_version="test-v1",
        output_kind="overview",
    )


def _response(product_ids: list[str]) -> httpx.Response:
    content = io.BytesIO()
    with tarfile.open(fileobj=content, mode="w") as archive:
        for name, data in (
            ("default.tif", b"geotiff-placeholder"),
            ("userdata.json", json.dumps({"productIds": product_ids}).encode()),
        ):
            member = tarfile.TarInfo(name)
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
    return httpx.Response(
        200,
        headers={"content-type": "application/x-tar"},
        content=content.getvalue(),
    )


@pytest.mark.parametrize("sensor", [Sensor.SENTINEL_1, Sensor.SENTINEL_2])
def test_process_request_selects_exact_product_and_returns_provenance(
    sensor: Sensor,
) -> None:
    payload = build_process_request(_request(sensor))
    data_filter = payload["input"]["data"][0]["dataFilter"]

    assert "ids" not in data_filter
    assert data_filter["timeRange"] == {
        "from": "2026-09-24T02:25:00Z",
        "to": "2026-09-24T04:26:00Z",
    }
    assert data_filter["mosaickingOrder"] == (
        "mostRecent" if sensor is Sensor.SENTINEL_1 else "leastCC"
    )
    assert "preProcessScenes" in payload["evalscript"]
    assert "SELECTED_PRODUCT.SAFE" in payload["evalscript"]
    assert payload["output"]["responses"][1]["identifier"] == "userdata"


def test_process_response_requires_provider_scene_identity() -> None:
    request = _request()
    assert _verified_response_raster(_response(["SELECTED_PRODUCT.SAFE"]), request) == (
        b"geotiff-placeholder",
        ("SELECTED_PRODUCT",),
    )

    with pytest.raises(ProcessRenderingError, match="source-product identity"):
        _verified_response_raster(_response(["OTHER_PRODUCT.SAFE"]), request)


def test_readiness_requires_authenticated_processing_with_public_fallback() -> None:
    workflow = GroundImageryArtifactWorkflow(
        GroundImageryRegionResolver(GeodesicGeometryEngine()),
        renderer=object(),
        authenticated_processing_available=False,
    )

    assert workflow.readiness()["state"] == "credentials_required"
