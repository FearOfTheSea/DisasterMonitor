import json
import zipfile
from datetime import UTC, datetime

from disaster_monitor.application.ground_imagery.comparisons import (
    GroundComparisonBuilder,
)
from disaster_monitor.application.ground_imagery.exports import (
    GroundExportBundleBuilder,
)
from disaster_monitor.application.ports.ground_imagery.rendering import ImageryGrid
from disaster_monitor.domain.imagery.regions import polygon_from_geojson

NOW = datetime(2026, 9, 15, tzinfo=UTC)
GRID = ImageryGrid("EPSG:32648", 0, 0, 1000, 1000, 10, 100, 100, "10m")
REGION = polygon_from_geojson(
    {
        "type": "Polygon",
        "coordinates": [[[106, 10], [107, 10], [107, 11], [106, 11], [106, 10]]],
    }
)


def test_comparison_manifest_records_reproducible_matched_grid_and_masks() -> None:
    manifest = GroundComparisonBuilder().build(
        comparison_id="comparison:1",
        before_product_id="S2-before",
        after_product_id="S2-after",
        before_capture=datetime(2026, 9, 1, tzinfo=UTC),
        after_capture=datetime(2026, 9, 14, tzinfo=UTC),
        before_checksum="a" * 64,
        after_checksum="b" * 64,
        before_grid=GRID,
        after_grid=GRID,
        recipe_version="s2-natural-color-v2",
        coverage_mask_version="s2-cloud-mask-v3",
        before_mask_checksum="c" * 64,
        after_mask_checksum="d" * 64,
        normalization="shared-p2-p98-reflectance",
        derived_metrics=(("valid_overlap_fraction", 0.82),),
        created_at=NOW,
    )

    assert manifest.grid == GRID
    assert manifest.before.product_id == "S2-before"
    assert manifest.after.mask_checksum == "d" * 64
    assert manifest.view_modes == ("side_by_side", "swipe")


def test_export_bundle_packages_only_explicit_artifacts_and_metadata(tmp_path) -> None:
    cog = tmp_path / "before.tif"
    preview = tmp_path / "preview.png"
    cog.write_bytes(b"cog")
    preview.write_bytes(b"png")
    manifest = GroundComparisonBuilder().build(
        comparison_id="comparison:1",
        before_product_id="before",
        after_product_id="after",
        before_capture=datetime(2026, 9, 1, tzinfo=UTC),
        after_capture=datetime(2026, 9, 14, tzinfo=UTC),
        before_checksum="a" * 64,
        after_checksum="b" * 64,
        before_grid=GRID,
        after_grid=GRID,
        recipe_version="recipe-v1",
        coverage_mask_version="mask-v1",
        before_mask_checksum="c" * 64,
        after_mask_checksum="d" * 64,
        normalization="none",
        derived_metrics=(),
        created_at=NOW,
    )

    output = GroundExportBundleBuilder().build(
        output_path=tmp_path / "bundle.zip",
        incident_id="earthquake:1",
        region=REGION,
        comparison=manifest,
        cogs=(cog,),
        previews=(preview,),
    )

    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
        assert names == {
            "cogs/before.tif",
            "previews/preview.png",
            "region.geojson",
            "comparison-manifest.json",
            "README.json",
        }
        readme = json.loads(archive.read("README.json"))
    assert readme["credentials_included"] is False
    assert readme["incident_id"] == "earthquake:1"
