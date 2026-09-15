"""Deterministic local asset/evidence intersection policy."""

import hashlib
from datetime import datetime

from disaster_monitor.domain.imagery.regions import (
    contains_coordinate,
    geometries_intersect,
    path_intersects_geometry,
)
from disaster_monitor.domain.spatial_watches import (
    LocalAsset,
    WatchFinding,
    WatchGeometryEvidence,
    WatchGeometryRole,
    WatchTriggerPolicy,
    coordinate_distance_km,
)

_ROLE_LABEL = {
    WatchGeometryRole.OBSERVED_HAZARD: "an observed hazard area",
    WatchGeometryRole.FORECAST_HAZARD: "a forecast hazard area",
    WatchGeometryRole.MODELLED_HAZARD: "a modelled hazard area",
    WatchGeometryRole.OFFICIAL_WARNING: "an official warning area",
}


class AssetExposureWatchEvaluator:
    def evaluate(
        self,
        *,
        watch_id: str,
        evidence: WatchGeometryEvidence,
        assets: tuple[LocalAsset, ...],
        policy: WatchTriggerPolicy,
        evaluated_at: datetime,
    ) -> tuple[WatchFinding, ...]:
        return tuple(
            finding
            for asset in sorted(assets, key=lambda item: item.asset_id)
            if (
                finding := self._finding(
                    watch_id, evidence, asset, policy, evaluated_at
                )
            )
            is not None
        )

    def _finding(
        self,
        watch_id: str,
        evidence: WatchGeometryEvidence,
        asset: LocalAsset,
        policy: WatchTriggerPolicy,
        evaluated_at: datetime,
    ) -> WatchFinding | None:
        intersects = (
            contains_coordinate(evidence.geometry, asset.coordinate)
            if asset.coordinate is not None
            else geometries_intersect(evidence.geometry, asset.geometry)
            if asset.geometry is not None
            else path_intersects_geometry(asset.route, evidence.geometry)
        )
        distance = 0.0 if intersects else _vertex_distance(asset, evidence)
        if not intersects and distance > policy.max_distance_km:
            return None
        geometry_hash = evidence.geometry.sha256()
        material = "|".join(
            (
                watch_id,
                asset.asset_id,
                asset.version,
                evidence.evidence_id,
                evidence.geometry_version,
                geometry_hash,
                f"{policy.max_distance_km:.6f}",
            )
        )
        relationship = "intersects" if intersects else f"is within {distance:.1f} km of"
        return WatchFinding(
            finding_id=f"asset-watch-finding:{hashlib.sha256(material.encode()).hexdigest()[:24]}",
            watch_id=watch_id,
            asset_id=asset.asset_id,
            asset_name=asset.name,
            asset_version=asset.version,
            evidence_id=evidence.evidence_id,
            source_id=evidence.source_id,
            role=evidence.role,
            geometry_version=evidence.geometry_version,
            geometry_hash=geometry_hash,
            distance_km=distance,
            created_at=evaluated_at,
            summary=f"{asset.name} {relationship} {_ROLE_LABEL[evidence.role]}",
        )


def _vertex_distance(asset: LocalAsset, evidence: WatchGeometryEvidence) -> float:
    asset_coordinates = (
        (asset.coordinate,)
        if asset.coordinate is not None
        else asset.route
        if asset.route
        else tuple(
            coordinate
            for polygon in asset.geometry.polygons
            for coordinate in polygon.exterior.coordinates
        )
        if asset.geometry is not None
        else ()
    )
    evidence_coordinates = tuple(
        coordinate
        for polygon in evidence.geometry.polygons
        for coordinate in polygon.exterior.coordinates
    )
    return min(
        coordinate_distance_km(first, second)
        for first in asset_coordinates
        for second in evidence_coordinates
    )
