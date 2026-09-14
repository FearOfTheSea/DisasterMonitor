"""Application-owned contracts for selectable satellite raster imagery."""

from dataclasses import dataclass
from typing import Literal, Protocol

SatelliteTemporalMode = Literal["daily", "subdaily", "fixed"]
SatelliteAccessMode = Literal["direct_gibs", "api"]
SatelliteRightsAccessModel = Literal["public", "free_account", "self_hosted", "paid"]


@dataclass(frozen=True, slots=True)
class SatelliteImageryProduct:
    """Credential-free capabilities for one selectable imagery source."""

    source_id: str
    display_name: str
    provider_id: str
    provider_name: str
    temporal_mode: SatelliteTemporalMode
    attribution: str
    maximum_useful_zoom: int
    access_mode: SatelliteAccessMode
    available: bool
    temporal_step_minutes: int | None = None
    rights_id: str = "nasa-gibs"
    access_model: SatelliteRightsAccessModel = "public"
    license_name: str = ""


@dataclass(frozen=True, slots=True)
class SatelliteTileRequest:
    provider_id: str
    source_id: str
    z: int
    x: int
    y: int
    observation_time: str | None


@dataclass(frozen=True, slots=True)
class SatelliteRasterTile:
    content: bytes
    media_type: Literal["image/jpeg", "image/png"]


class SatelliteImageryProvider(Protocol):
    @property
    def provider_id(self) -> str: ...

    @property
    def products(self) -> tuple[SatelliteImageryProduct, ...]: ...

    async def fetch_tile(
        self, request: SatelliteTileRequest
    ) -> SatelliteRasterTile: ...

    async def aclose(self) -> None: ...
