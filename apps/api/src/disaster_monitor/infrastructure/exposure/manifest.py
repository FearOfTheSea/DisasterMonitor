"""Validate operator-supplied datasets before wiring desktop evidence."""

import csv
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Self

import rasterio
from pydantic import BaseModel, ConfigDict, Field, model_validator

from disaster_monitor.application.ports.exposure import PopulationExposureProvider
from disaster_monitor.domain.exposure import (
    ExposureDataset,
    ExposureDatasetRole,
    ExposureGeometry,
    InfrastructureAsset,
    OsmCompletenessIndicator,
    PopulationExposureEstimate,
)
from disaster_monitor.infrastructure.exposure.local_osm import LocalOsmAssetExposure
from disaster_monitor.infrastructure.exposure.population_raster import (
    PopulationRasterExposure,
)
from disaster_monitor.infrastructure.hazard_context.inform import InformRiskDataset


class DatasetEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["worldpop", "ghsl", "osm", "inform"]
    path: str = Field(min_length=1)
    version: str = Field(min_length=1)
    vintage: int = Field(ge=1900, le=2200)
    sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    license_name: str = Field(min_length=1)
    publisher: str = Field(min_length=1)
    source_url: str = Field(pattern=r"^https://")
    coverage: tuple[float, float, float, float]
    country_codes: tuple[str, ...] = ()
    resolution_m: float = Field(default=1000, gt=0, le=100_000)

    @model_validator(mode="after")
    def validate_coverage(self) -> Self:
        west, south, east, north = self.coverage
        if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
            raise ValueError("Dataset coverage must be a finite WGS84 bounding box.")
        if any(
            len(code) != 3 or not code.isupper() or not code.isalpha()
            for code in self.country_codes
        ):
            raise ValueError("Dataset country codes must be ISO alpha-3 codes.")
        return self


class DatasetManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1]
    datasets: tuple[DatasetEntry, ...] = Field(max_length=8)


@dataclass(frozen=True, slots=True)
class DatasetServices:
    population_providers: tuple[PopulationExposureProvider, ...] = ()
    asset_provider: LocalOsmAssetExposure | None = None
    baseline: InformRiskDataset | None = None
    limitations: tuple[str, ...] = ()


class CoveredPopulation:
    def __init__(self, provider: PopulationExposureProvider, entry: DatasetEntry):
        self._provider, self._entry = provider, entry

    async def estimate(self, geometry: ExposureGeometry) -> PopulationExposureEstimate:
        _require_coverage(geometry, self._entry.coverage)
        return await self._provider.estimate(geometry)


class CoveredOsm(LocalOsmAssetExposure):
    def __init__(self, path: Path, entry: DatasetEntry):
        super().__init__(path, extract_version=entry.version)
        self._entry = entry
        # Validate before admission; completeness needs source metadata.
        self._document()

    async def intersecting_assets(
        self, geometry: ExposureGeometry
    ) -> tuple[InfrastructureAsset, ...]:
        _require_coverage(geometry, self._entry.coverage)
        return await super().intersecting_assets(geometry)

    async def completeness(
        self, geometry: ExposureGeometry
    ) -> OsmCompletenessIndicator:
        _require_coverage(geometry, self._entry.coverage)
        return await super().completeness(geometry)


def _require_coverage(
    geometry: ExposureGeometry, coverage: tuple[float, float, float, float]
) -> None:
    west, south, east, north = coverage
    if any(
        not (west <= point.longitude <= east and south <= point.latitude <= north)
        for polygon in geometry.geometry.polygons
        for point in polygon.exterior.coordinates
    ):
        raise ValueError("Requested geometry is outside the declared dataset coverage.")


def load_dataset_services(path: Path | None) -> DatasetServices:
    if path is None:
        return DatasetServices(
            limitations=("Operator dataset manifest is not configured.",)
        )
    try:
        if not path.is_file() or path.stat().st_size > 2_000_000:
            raise ValueError("Dataset manifest is missing or exceeds 2 MB.")
        manifest = DatasetManifest.model_validate_json(path.read_text(encoding="utf-8"))
        root = path.resolve().parent
        population = []
        osm = None
        baseline = None
        seen = set()
        for entry in manifest.datasets:
            if entry.kind in seen:
                raise ValueError("Duplicate dataset kind in manifest.")
            seen.add(entry.kind)
            local = (root / entry.path).resolve()
            if not local.is_relative_to(root) or not local.is_file():
                raise ValueError(
                    "Dataset path must name a file within the manifest directory."
                )
            with local.open("rb") as source:
                checksum = hashlib.file_digest(source, "sha256").hexdigest()
            if checksum != entry.sha256.lower():
                raise ValueError(f"{entry.kind} checksum does not match the manifest.")
            if entry.kind in ("worldpop", "ghsl"):
                provider = PopulationRasterExposure(
                    local,
                    ExposureDataset(
                        entry.kind + "-" + entry.version,
                        entry.publisher,
                        entry.version,
                        entry.vintage,
                        entry.resolution_m,
                        entry.license_name,
                        entry.source_url,
                        ExposureDatasetRole.PRIMARY
                        if entry.kind == "worldpop"
                        else ExposureDatasetRole.SECONDARY,
                        (
                            "Modelled population counts per cell; "
                            "vintage and allocation "
                            "are uncertain."
                        ),
                    ),
                )
                population.append(CoveredPopulation(provider, entry))
            elif entry.kind == "osm":
                osm = CoveredOsm(local, entry)
            else:
                baseline = InformRiskDataset(local, version=entry.version)
                with local.open(encoding="utf-8", newline="") as source:
                    codes = [
                        row.get("iso3", "").strip().upper()
                        for row in csv.DictReader(source)
                    ]
                if len(codes) != len(set(codes)) or any(
                    len(code) != 3 for code in codes
                ):
                    raise ValueError(
                        "INFORM contains invalid or duplicate country identities."
                    )
                if entry.country_codes and set(codes) != set(entry.country_codes):
                    raise ValueError("INFORM countries do not match declared coverage.")
                for code in codes:
                    context = baseline.lookup(code)
                    if context is None or context.vintage != entry.vintage:
                        raise ValueError("INFORM vintage does not match the manifest.")
        return DatasetServices(
            population_providers=tuple(population),
            asset_provider=osm,
            baseline=baseline,
        )
    except (
        csv.Error,
        ValueError,
        OSError,
        KeyError,
        TypeError,
        rasterio.errors.RasterioError,
    ) as error:
        return DatasetServices(
            limitations=(f"Dataset manifest was not admitted: {error}",)
        )
