"""Rights-gated deterministic MBTiles packaging for offline review."""

from __future__ import annotations

import hashlib
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True, slots=True)
class OfflineTile:
    zoom: int
    x: int
    y: int
    content: bytes

    def __post_init__(self) -> None:
        maximum = 2**self.zoom
        if self.zoom < 0 or not 0 <= self.x < maximum or not 0 <= self.y < maximum:
            raise ValueError("Offline tile coordinates are invalid.")
        if not self.content:
            raise ValueError("Offline tiles must not be empty.")


@dataclass(frozen=True, slots=True)
class OfflinePackageManifest:
    package_id: str
    format: str
    tile_count: int
    bounds: tuple[float, float, float, float]
    attribution: str
    source_license: str
    sha256: str


def build_mbtiles_package(
    destination: Path,
    *,
    tiles: tuple[OfflineTile, ...],
    package_id: str,
    name: str,
    attribution: str,
    source_license: str,
    redistribution_permitted: bool,
    bounds: tuple[float, float, float, float],
    package_kind: Literal["overlay", "baselayer"] = "overlay",
) -> OfflinePackageManifest:
    if not redistribution_permitted:
        raise ValueError("The source license does not permit offline redistribution.")
    if not tiles or not all(
        value.strip() for value in (package_id, name, attribution, source_license)
    ):
        raise ValueError("Offline packages require tiles and complete attribution.")
    west, south, east, north = bounds
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise ValueError("Offline package bounds are invalid.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    if temporary.exists():
        temporary.unlink()
    try:
        connection = sqlite3.connect(temporary)
        with connection:
            connection.executescript(
                """
                CREATE TABLE metadata (name TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE tiles (
                    zoom_level INTEGER NOT NULL,
                    tile_column INTEGER NOT NULL,
                    tile_row INTEGER NOT NULL,
                    tile_data BLOB NOT NULL,
                    PRIMARY KEY (zoom_level, tile_column, tile_row)
                );
                """
            )
            metadata = {
                "name": name,
                "format": "png",
                "bounds": ",".join(str(value) for value in bounds),
                "attribution": attribution,
                "license": source_license,
                "package_id": package_id,
                "type": package_kind,
                "version": "1",
            }
            connection.executemany(
                "INSERT INTO metadata(name, value) VALUES (?, ?)", metadata.items()
            )
            connection.executemany(
                "INSERT INTO tiles(zoom_level, tile_column, tile_row, tile_data) "
                "VALUES (?, ?, ?, ?)",
                (
                    (tile.zoom, tile.x, (2**tile.zoom - 1) - tile.y, tile.content)
                    for tile in sorted(
                        tiles, key=lambda item: (item.zoom, item.x, item.y)
                    )
                ),
            )
        connection.close()
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    return OfflinePackageManifest(
        package_id=package_id,
        format="mbtiles-1.3",
        tile_count=len(tiles),
        bounds=bounds,
        attribution=attribution,
        source_license=source_license,
        sha256=digest,
    )


def build_local_basemap_package(
    destination: Path,
    *,
    tiles: tuple[OfflineTile, ...],
    package_id: str,
    name: str,
    attribution: str,
    source_license: str,
    redistribution_permitted: bool,
    bounds: tuple[float, float, float, float],
) -> OfflinePackageManifest:
    """Build an optional local MBTiles basemap under the same rights gate."""
    return build_mbtiles_package(
        destination,
        tiles=tiles,
        package_id=package_id,
        name=name,
        attribution=attribution,
        source_license=source_license,
        redistribution_permitted=redistribution_permitted,
        bounds=bounds,
        package_kind="baselayer",
    )


__all__ = [
    "OfflinePackageManifest",
    "OfflineTile",
    "build_local_basemap_package",
    "build_mbtiles_package",
]
