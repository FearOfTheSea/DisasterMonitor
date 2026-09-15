"""Private local JSON persistence for operator-defined watch geometries."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from disaster_monitor.domain.imagery.regions import Coordinate, polygon_from_geojson
from disaster_monitor.domain.spatial_watches import (
    AreaOfInterestScope,
    LocalAsset,
    LocalAssetKind,
    SpatialInputKind,
)


class LocalSpatialWatchStore:
    """Persist only on the local filesystem with owner-only permissions."""

    def __init__(self, path: Path) -> None:
        if path.name in {"", ".", ".."}:
            raise ValueError("Spatial watch storage requires a concrete file path.")
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        self._lock = asyncio.Lock()

    async def save_scope(self, scope: AreaOfInterestScope) -> None:
        async with self._lock:
            document = self._read()
            values = {
                str(item["scope_id"]): item for item in _list(document.get("scopes"))
            }
            values[scope.scope_id] = _scope_document(scope)
            document["scopes"] = [values[key] for key in sorted(values)]
            self._write(document)

    async def list_scopes(self) -> tuple[AreaOfInterestScope, ...]:
        async with self._lock:
            return tuple(_scope(item) for item in _list(self._read().get("scopes")))

    async def delete_scope(self, scope_id: str) -> bool:
        async with self._lock:
            document = self._read()
            values = _list(document.get("scopes"))
            retained = [item for item in values if item.get("scope_id") != scope_id]
            if len(retained) == len(values):
                return False
            document["scopes"] = retained
            self._write(document)
            return True

    async def save_asset(self, asset: LocalAsset) -> None:
        async with self._lock:
            document = self._read()
            values = {
                str(item["asset_id"]): item for item in _list(document.get("assets"))
            }
            values[asset.asset_id] = _asset_document(asset)
            document["assets"] = [values[key] for key in sorted(values)]
            self._write(document)

    async def list_assets(self) -> tuple[LocalAsset, ...]:
        async with self._lock:
            return tuple(_asset(item) for item in _list(self._read().get("assets")))

    async def delete_asset(self, asset_id: str) -> bool:
        async with self._lock:
            document = self._read()
            values = _list(document.get("assets"))
            retained = [item for item in values if item.get("asset_id") != asset_id]
            if len(retained) == len(values):
                return False
            document["assets"] = retained
            self._write(document)
            return True

    def _read(self) -> dict[str, Any]:
        if not self._path.exists():
            return {"schema_version": "spatial-watches.v1", "scopes": [], "assets": []}
        document = json.loads(self._path.read_text(encoding="utf-8"))
        if (
            not isinstance(document, dict)
            or document.get("schema_version") != "spatial-watches.v1"
        ):
            raise ValueError("Local spatial watch document has an unsupported schema.")
        _list(document.get("scopes"))
        _list(document.get("assets"))
        return document

    def _write(self, document: dict[str, Any]) -> None:
        temporary = self._path.with_suffix(f"{self._path.suffix}.partial")
        temporary.write_text(
            json.dumps(document, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        temporary.chmod(0o600)
        os.replace(temporary, self._path)
        self._path.chmod(0o600)


def _list(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError("Local spatial watch collection is invalid.")
    return value


def _scope_document(value: AreaOfInterestScope) -> dict[str, object]:
    return {
        "scope_id": value.scope_id,
        "name": value.name,
        "input_kind": value.input_kind.value,
        "geometry": value.geometry.as_geojson(),
        "version": value.version,
        "updated_at": value.updated_at.isoformat(),
    }


def _scope(value: Mapping[str, Any]) -> AreaOfInterestScope:
    return AreaOfInterestScope(
        scope_id=str(value["scope_id"]),
        name=str(value["name"]),
        input_kind=SpatialInputKind(str(value["input_kind"])),
        geometry=polygon_from_geojson(_mapping(value["geometry"])),
        version=str(value["version"]),
        updated_at=datetime.fromisoformat(str(value["updated_at"])),
    )


def _asset_document(value: LocalAsset) -> dict[str, object]:
    return {
        "asset_id": value.asset_id,
        "name": value.name,
        "kind": value.kind.value,
        "version": value.version,
        "updated_at": value.updated_at.isoformat(),
        "coordinate": (
            value.coordinate.as_geojson() if value.coordinate is not None else None
        ),
        "geometry": value.geometry.as_geojson() if value.geometry is not None else None,
        "route": [item.as_geojson() for item in value.route],
    }


def _asset(value: Mapping[str, Any]) -> LocalAsset:
    raw_coordinate = value.get("coordinate")
    coordinate = (
        Coordinate(float(raw_coordinate[1]), float(raw_coordinate[0]))
        if isinstance(raw_coordinate, list) and len(raw_coordinate) == 2
        else None
    )
    raw_route = value.get("route")
    route = (
        tuple(
            Coordinate(float(item[1]), float(item[0]))
            for item in raw_route
            if isinstance(item, list) and len(item) == 2
        )
        if isinstance(raw_route, list)
        else ()
    )
    raw_geometry = value.get("geometry")
    return LocalAsset(
        asset_id=str(value["asset_id"]),
        name=str(value["name"]),
        kind=LocalAssetKind(str(value["kind"])),
        version=str(value["version"]),
        updated_at=datetime.fromisoformat(str(value["updated_at"])),
        coordinate=coordinate,
        geometry=(
            polygon_from_geojson(_mapping(raw_geometry))
            if raw_geometry is not None
            else None
        ),
        route=route,
    )


def _mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("Local spatial watch geometry is invalid.")
    return value
