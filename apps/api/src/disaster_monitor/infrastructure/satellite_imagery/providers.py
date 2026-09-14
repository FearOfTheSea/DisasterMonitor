"""Public NASA GIBS catalog for the general map."""

from __future__ import annotations

from disaster_monitor.application.ports.satellite_imagery import (
    SatelliteImageryProduct,
    SatelliteRasterTile,
    SatelliteTemporalMode,
    SatelliteTileRequest,
)
from disaster_monitor.application.satellite_imagery import SatelliteImageryInputError

_GIBS_ATTRIBUTION = (
    "We acknowledge the use of imagery provided by services from NASA's Global "
    "Imagery Browse Services (GIBS), part of NASA's Earth Science Data and "
    "Information System (ESDIS)."
)


class NasaGibsImageryProvider:
    """Credential-free catalog entries loaded directly by the browser from GIBS."""

    provider_id = "nasa-gibs"

    @property
    def products(self) -> tuple[SatelliteImageryProduct, ...]:
        return (
            self._product(
                source_id="nasa-viirs-snpp-true-color",
                display_name="NASA VIIRS Suomi-NPP True Color",
                temporal_mode="daily",
                maximum_useful_zoom=9,
            ),
            self._product(
                source_id="nasa-modis-terra-true-color",
                display_name="NASA MODIS Terra True Color",
                temporal_mode="daily",
                maximum_useful_zoom=9,
            ),
            self._product(
                source_id="nasa-modis-aqua-true-color",
                display_name="NASA MODIS Aqua True Color",
                temporal_mode="daily",
                maximum_useful_zoom=9,
            ),
            self._product(
                source_id="nasa-goes-east-geocolor",
                display_name="NASA GOES-East GeoColor",
                temporal_mode="subdaily",
                temporal_step_minutes=10,
                maximum_useful_zoom=7,
            ),
            self._product(
                source_id="nasa-goes-west-geocolor",
                display_name="NASA GOES-West GeoColor",
                temporal_mode="subdaily",
                temporal_step_minutes=10,
                maximum_useful_zoom=7,
            ),
            self._product(
                source_id="nasa-himawari-9-visible",
                display_name="NASA Himawari-9 visible imagery",
                temporal_mode="subdaily",
                temporal_step_minutes=10,
                maximum_useful_zoom=7,
            ),
        )

    def _product(
        self,
        *,
        source_id: str,
        display_name: str,
        temporal_mode: SatelliteTemporalMode,
        maximum_useful_zoom: int,
        temporal_step_minutes: int | None = None,
    ) -> SatelliteImageryProduct:
        return SatelliteImageryProduct(
            source_id=source_id,
            display_name=display_name,
            provider_id=self.provider_id,
            provider_name="NASA GIBS",
            temporal_mode=temporal_mode,
            temporal_step_minutes=temporal_step_minutes,
            attribution=_GIBS_ATTRIBUTION,
            maximum_useful_zoom=maximum_useful_zoom,
            access_mode="direct_gibs",
            available=True,
            rights_id=source_id,
            access_model="public",
            license_name="NASA GIBS data and imagery terms",
        )

    async def fetch_tile(self, request: SatelliteTileRequest) -> SatelliteRasterTile:
        raise SatelliteImageryInputError("NASA GIBS tiles are loaded directly.")

    async def aclose(self) -> None:
        return None
