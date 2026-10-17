import hashlib
import json

import pytest

from disaster_monitor.infrastructure.exposure.manifest import load_dataset_services


def manifest(tmp_path, checksum=None):
    data = tmp_path / "inform.csv"
    data.write_text(
        "iso3,place_name,aggregation_level,vintage,risk,vulnerability,coping_capacity"
        "\nVNM,Vietnam,country,2025,4,5,6\n"
    )
    path = tmp_path / "datasets.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "datasets": [
                    {
                        "kind": "inform",
                        "path": "inform.csv",
                        "version": "2025",
                        "vintage": 2025,
                        "sha256": checksum
                        or hashlib.sha256(data.read_bytes()).hexdigest(),
                        "license_name": "CC BY 4.0",
                        "publisher": "INFORM",
                        "source_url": "https://drmkc.jrc.ec.europa.eu/inform-index",
                        "coverage": [-180, -90, 180, 90],
                        "country_codes": ["VNM"],
                    }
                ],
            }
        )
    )
    return path


def test_manifest_wires_valid_inform(tmp_path):
    services = load_dataset_services(manifest(tmp_path))
    assert services.baseline.lookup("VNM").vintage == 2025
    assert services.baseline.lookup("USA") is None


def test_manifest_csv_parser_failure_is_a_configuration_gap(tmp_path):
    path = manifest(tmp_path)
    document = json.loads(path.read_text(encoding="utf-8"))
    data = tmp_path / "inform.csv"
    data.write_text("iso3\n" + "V" * 200_000 + "\n", encoding="utf-8")
    document["datasets"][0]["sha256"] = hashlib.sha256(data.read_bytes()).hexdigest()
    path.write_text(json.dumps(document), encoding="utf-8")

    services = load_dataset_services(path)

    assert services.baseline is None
    assert "manifest was not admitted" in services.limitations[0].lower()


def test_manifest_rejects_corrupt_dataset_and_does_not_abort_app(tmp_path):
    services = load_dataset_services(manifest(tmp_path, "0" * 64))
    assert services.baseline is None
    assert "checksum" in services.limitations[0].lower()


def test_missing_manifest_is_unconfigured():
    services = load_dataset_services(None)
    assert services.population_providers == ()
    assert services.asset_provider is None
    assert services.baseline is None


@pytest.mark.parametrize("fault", ["missing_file", "corrupt_csv", "escape_path"])
def test_invalid_operator_files_are_rejected_with_a_gap(tmp_path, fault):
    path = manifest(tmp_path)
    document = json.loads(path.read_text())
    data = tmp_path / "inform.csv"
    if fault == "missing_file":
        document["datasets"][0]["path"] = "missing.csv"
    elif fault == "escape_path":
        document["datasets"][0]["path"] = "../inform.csv"
    else:
        data.write_text("iso3,vintage\nVNM,not-a-year\n")
        document["datasets"][0]["sha256"] = hashlib.sha256(
            data.read_bytes()
        ).hexdigest()
    path.write_text(json.dumps(document))
    services = load_dataset_services(path)
    assert services.baseline is None
    assert services.limitations


async def test_declared_population_coverage_rejects_an_outside_inspection():
    from datetime import UTC, datetime

    from disaster_monitor.domain.exposure import ExposureGeometry, ExposureGeometryRole
    from disaster_monitor.domain.imagery.regions import polygon_from_geojson
    from disaster_monitor.infrastructure.exposure.manifest import (
        CoveredPopulation,
        DatasetEntry,
    )

    class Population:
        async def estimate(self, geometry):
            raise AssertionError("Out-of-coverage data must not be read")

    entry = DatasetEntry(
        kind="worldpop",
        path="population.tif",
        version="2025",
        vintage=2025,
        sha256="0" * 64,
        license_name="CC BY 4.0",
        publisher="WorldPop",
        source_url="https://www.worldpop.org/",
        coverage=(100, 0, 101, 1),
    )
    geometry = polygon_from_geojson(
        {
            "type": "Polygon",
            "coordinates": [
                [
                    [106, 10],
                    [106.1, 10],
                    [106.1, 10.1],
                    [106, 10.1],
                    [106, 10],
                ]
            ],
        }
    )
    with pytest.raises(ValueError, match="outside"):
        await CoveredPopulation(Population(), entry).estimate(
            ExposureGeometry(
                geometry,
                ExposureGeometryRole.OPERATOR_INSPECTION,
                "operator",
                geometry.sha256(),
                datetime.now(UTC),
            )
        )
