"""Resolve incident geography into a bounded, provenance-bearing inspection region."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256

from disaster_monitor.application.ports.ground_imagery.geometry import (
    GeometryComputationError,
    RegionGeometryEngine,
)
from disaster_monitor.application.ports.ground_imagery.incidents import (
    IncidentImageryContext,
)
from disaster_monitor.application.ports.ground_imagery.places import (
    PlaceBoundaryLookup,
)
from disaster_monitor.application.ports.ground_imagery.rendering import ImageryGrid
from disaster_monitor.domain.disaster import Disaster
from disaster_monitor.domain.imagery.observations import Sensor
from disaster_monitor.domain.imagery.regions import (
    AssociationStatus,
    Coordinate,
    ImageryRegionVersion,
    MultiPolygon,
    RegionEvidence,
    RegionRole,
    RegionSource,
    RegionSourceKind,
)

DEFAULT_CONTEXT_MARGIN_KM = 2.0
HAZARD_FALLBACK_RADII_KM: dict[Disaster, float] = {
    Disaster.FLOOD: 15.0,
    Disaster.WILDFIRE: 10.0,
    Disaster.EARTHQUAKE: 50.0,
    Disaster.LANDSLIDE: 5.0,
    Disaster.TROPICAL_CYCLONE: 30.0,
    Disaster.VOLCANIC_ERUPTION: 15.0,
}


class RegionResolutionState(StrEnum):
    """Outcome of selecting a geographic subject for imagery."""

    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    NEEDS_REGION = "needs_region"


@dataclass(frozen=True, slots=True)
class RegionResolution:
    """Region result plus selectable alternatives and honest diagnostics."""

    state: RegionResolutionState
    region: ImageryRegionVersion | None
    alternatives: tuple[RegionEvidence, ...] = ()
    warnings: tuple[str, ...] = ()
    reason_code: str | None = None


class GroundImageryRegionResolver:
    """Apply the documented source-priority policy without merging events."""

    def __init__(
        self,
        geometry: RegionGeometryEngine,
        *,
        place_lookup: PlaceBoundaryLookup | None = None,
        context_margin_km: float = DEFAULT_CONTEXT_MARGIN_KM,
    ) -> None:
        if not 0 <= context_margin_km <= 20:
            raise ValueError("The imagery context margin must be between 0 and 20 km.")
        self._geometry = geometry
        self._place_lookup = place_lookup
        self._context_margin_km = context_margin_km

    async def resolve_async(
        self,
        context: IncidentImageryContext,
        *,
        user_region: MultiPolygon | None = None,
        context_margin_km: float | None = None,
        fallback_radius_km: float | None = None,
    ) -> RegionResolution:
        """Resolve a region with optional administrative lookup when needed."""
        margin = self._validated_margin(context_margin_km)
        if user_region is not None:
            return self._resolved(
                context,
                user_region,
                source_footprints=(self._user_evidence(context, user_region),),
                association=AssociationStatus.USER_SELECTED,
                margin_km=margin,
                point_fallback=False,
            )

        candidates = self._priority_candidates(context)
        if candidates:
            selected = self._select_candidates(candidates)
            if selected is None:
                return RegionResolution(
                    state=RegionResolutionState.AMBIGUOUS,
                    region=None,
                    alternatives=tuple(candidates),
                    reason_code="ambiguous_region",
                    warnings=(
                        "Multiple plausible geographic components are available. "
                        "Choose a component before preparing imagery.",
                    ),
                )
            geometry = self._combine_geometry(selected)
            association = (
                AssociationStatus.CONFIRMED
                if any(
                    item.association is AssociationStatus.CONFIRMED for item in selected
                )
                else AssociationStatus.POSSIBLE
            )
            return self._resolved(
                context,
                geometry,
                source_footprints=tuple(selected),
                association=association,
                margin_km=margin,
                point_fallback=False,
            )

        place_candidates = await self._reported_place_candidates(context)
        if place_candidates:
            selected = self._select_candidates(place_candidates)
            if selected is None:
                return RegionResolution(
                    state=RegionResolutionState.AMBIGUOUS,
                    region=None,
                    alternatives=tuple(place_candidates),
                    reason_code="ambiguous_place_boundary",
                    warnings=(
                        "The reported place has multiple plausible administrative "
                        "boundaries. Choose one before preparing imagery.",
                    ),
                )
            return self._resolved(
                context,
                self._combine_geometry(selected),
                source_footprints=tuple(selected),
                association=AssociationStatus.POSSIBLE,
                margin_km=margin,
                point_fallback=False,
                warnings=(
                    "This region represents reported administrative context; it is "
                    "not a measured impact perimeter.",
                ),
            )

        if context.verified_point is not None and (
            context.disaster is not Disaster.TROPICAL_CYCLONE
            or context.verified_point_is_land_impact
        ):
            radius = (
                HAZARD_FALLBACK_RADII_KM[context.disaster]
                if fallback_radius_km is None
                else fallback_radius_km
            )
            if not 0 < radius <= 200:
                raise ValueError(
                    "The point fallback radius must be between 0 and 200 km."
                )
            source = RegionSource(
                source_id=f"incident:{context.incident_id}:point",
                source_kind=RegionSourceKind.VERIFIED_EVENT_POINT,
                publisher="Incident evidence",
                reference=context.incident_id,
            )
            point_evidence = RegionEvidence(
                evidence_id=f"point:{context.incident_id}",
                geometry=None,
                source=source,
                association=AssociationStatus.CONFIRMED,
                semantic_role="verified event point",
            )
            return self._resolved_point(
                context,
                context.verified_point,
                point_evidence,
                radius,
            )

        warnings = [
            (
                "No defensible impact, modeled, place, or verified-point geography "
                "is available. The incident remains visible, but imagery needs a "
                "selected region."
            ),
        ]
        if any(
            item.source.source_kind is RegionSourceKind.ACQUISITION_FOOTPRINT
            for item in context.evidence
        ):
            warnings.append(
                "Satellite acquisition footprints were ignored as geography; a tile "
                "center is not an event location."
            )
        return RegionResolution(
            state=RegionResolutionState.NEEDS_REGION,
            region=None,
            warnings=tuple(warnings),
            reason_code="needs_region",
        )

    def resolve(
        self,
        context: IncidentImageryContext,
        *,
        user_region: MultiPolygon | None = None,
        context_margin_km: float | None = None,
        fallback_radius_km: float | None = None,
    ) -> RegionResolution:
        """Resolve synchronously when no asynchronous place lookup is configured."""
        if self._place_lookup is not None and context.reported_places:
            raise RuntimeError(
                "A configured place lookup requires resolve_async so boundary "
                "downloads remain explicit and bounded."
            )
        return self._resolve_without_lookup(
            context,
            user_region=user_region,
            context_margin_km=context_margin_km,
            fallback_radius_km=fallback_radius_km,
        )

    def plan_grid(
        self,
        region: MultiPolygon,
        sensor: Sensor,
        *,
        overview: bool = True,
    ) -> ImageryGrid:
        """Delegate metric output-grid planning to the geometry adapter."""
        return self._geometry.plan_grid(region, sensor, overview=overview)

    async def aclose(self) -> None:
        close = getattr(self._place_lookup, "aclose", None)
        if close is not None:
            await close()

    def _resolve_without_lookup(
        self,
        context: IncidentImageryContext,
        *,
        user_region: MultiPolygon | None,
        context_margin_km: float | None,
        fallback_radius_km: float | None,
    ) -> RegionResolution:
        margin = self._validated_margin(context_margin_km)
        if user_region is not None:
            return self._resolved(
                context,
                user_region,
                source_footprints=(self._user_evidence(context, user_region),),
                association=AssociationStatus.USER_SELECTED,
                margin_km=margin,
                point_fallback=False,
            )
        candidates = self._priority_candidates(context)
        if candidates:
            selected = self._select_candidates(candidates)
            if selected is None:
                return RegionResolution(
                    state=RegionResolutionState.AMBIGUOUS,
                    region=None,
                    alternatives=tuple(candidates),
                    reason_code="ambiguous_region",
                    warnings=(
                        "Multiple plausible geographic components are available. "
                        "Choose a component before preparing imagery.",
                    ),
                )
            return self._resolved(
                context,
                self._combine_geometry(selected),
                source_footprints=tuple(selected),
                association=(
                    AssociationStatus.CONFIRMED
                    if any(
                        item.association is AssociationStatus.CONFIRMED
                        for item in selected
                    )
                    else AssociationStatus.POSSIBLE
                ),
                margin_km=margin,
                point_fallback=False,
            )
        if context.verified_point is not None and (
            context.disaster is not Disaster.TROPICAL_CYCLONE
            or context.verified_point_is_land_impact
        ):
            radius = (
                HAZARD_FALLBACK_RADII_KM[context.disaster]
                if fallback_radius_km is None
                else fallback_radius_km
            )
            if not 0 < radius <= 200:
                raise ValueError(
                    "The point fallback radius must be between 0 and 200 km."
                )
            source = RegionSource(
                source_id=f"incident:{context.incident_id}:point",
                source_kind=RegionSourceKind.VERIFIED_EVENT_POINT,
                publisher="Incident evidence",
                reference=context.incident_id,
            )
            point_evidence = RegionEvidence(
                evidence_id=f"point:{context.incident_id}",
                geometry=None,
                source=source,
                association=AssociationStatus.CONFIRMED,
                semantic_role="verified event point",
            )
            return self._resolved_point(
                context, context.verified_point, point_evidence, radius
            )
        warnings = [
            (
                "No defensible impact, modeled, place, or verified-point geography "
                "is available. The incident remains visible, but imagery needs a "
                "selected region."
            )
        ]
        if any(
            item.source.source_kind is RegionSourceKind.ACQUISITION_FOOTPRINT
            for item in context.evidence
        ):
            warnings.append(
                "Satellite acquisition footprints were ignored as geography; a "
                "tile center is not an event location."
            )
        return RegionResolution(
            state=RegionResolutionState.NEEDS_REGION,
            region=None,
            warnings=tuple(warnings),
            reason_code="needs_region",
        )

    async def _reported_place_candidates(
        self, context: IncidentImageryContext
    ) -> tuple[RegionEvidence, ...]:
        existing = tuple(
            item
            for item in context.evidence
            if item.geometry is not None
            and item.source.source_kind is RegionSourceKind.REPORTED_PLACE
            and item.association is not AssociationStatus.UNRELATED
        )
        if existing or self._place_lookup is None or context.country_code is None:
            return existing
        boundaries: list[RegionEvidence] = []
        for place in context.reported_places:
            matches = await self._place_lookup.find(
                name=place,
                country_code=context.country_code,
            )
            boundaries.extend(
                RegionEvidence(
                    evidence_id=f"boundary:{match.boundary_id}",
                    geometry=match.geometry,
                    source=match.source,
                    association=AssociationStatus.POSSIBLE,
                    semantic_role="reported administrative place",
                    place_name=match.name,
                    country_code=match.country_code,
                    derivation_inputs=(
                        match.boundary_id,
                        match.static_revision,
                        match.checksum,
                    ),
                )
                for match in matches
            )
        return tuple(boundaries)

    def _priority_candidates(
        self, context: IncidentImageryContext
    ) -> tuple[RegionEvidence, ...]:
        priority = {
            RegionSourceKind.MAPPED_IMPACT: 1,
            RegionSourceKind.OBSERVATION_MASK: 2,
            RegionSourceKind.MODELED_HAZARD: 3,
        }
        eligible = tuple(
            item
            for item in context.evidence
            if item.geometry is not None
            and item.source.source_kind in priority
            and item.association
            in {
                AssociationStatus.CONFIRMED,
                AssociationStatus.POSSIBLE,
            }
            and (
                context.disaster is not Disaster.TROPICAL_CYCLONE
                or item.source.source_kind is not RegionSourceKind.MODELED_HAZARD
                or context.modeled_hazard_is_land_impact
            )
        )
        if not eligible:
            return ()
        best = min(priority[item.source.source_kind] for item in eligible)
        return tuple(
            item for item in eligible if priority[item.source.source_kind] == best
        )

    @staticmethod
    def _select_candidates(
        candidates: tuple[RegionEvidence, ...],
    ) -> tuple[RegionEvidence, ...] | None:
        if len(candidates) == 1:
            return candidates
        source_keys = {
            (item.source.source_kind, item.source.source_id) for item in candidates
        }
        if len(source_keys) == 1:
            return tuple(sorted(candidates, key=lambda item: item.evidence_id))
        return None

    def _resolved(
        self,
        context: IncidentImageryContext,
        core: MultiPolygon,
        *,
        source_footprints: tuple[RegionEvidence, ...],
        association: AssociationStatus,
        margin_km: float,
        point_fallback: bool,
        warnings: tuple[str, ...] = (),
    ) -> RegionResolution:
        try:
            self._geometry.validate(core)
            inspection = (
                core if margin_km == 0 else self._geometry.buffer(core, margin_km)
            )
            self._geometry.validate(inspection)
        except GeometryComputationError as error:
            return RegionResolution(
                state=RegionResolutionState.NEEDS_REGION,
                region=None,
                warnings=(str(error),),
                reason_code="invalid_region",
            )
        source_ids = tuple(item.evidence_id for item in source_footprints)
        region_id = _region_id(context.incident_id, core, source_ids)
        return RegionResolution(
            state=RegionResolutionState.RESOLVED,
            region=ImageryRegionVersion(
                region_id=region_id,
                version=1,
                core=core,
                inspection=inspection,
                source_footprints=source_footprints,
                core_role=RegionRole.CORE,
                association=association,
                derivation_inputs=source_ids,
            ),
            warnings=(
                *warnings,
                *(
                    (
                        "The region is a point-derived inspection buffer, not an "
                        "estimated damage perimeter.",
                    )
                    if point_fallback
                    else ()
                ),
            ),
        )

    def _resolved_point(
        self,
        context: IncidentImageryContext,
        point: Coordinate,
        source: RegionEvidence,
        radius_km: float,
    ) -> RegionResolution:
        try:
            core = self._geometry.buffer_point(point, radius_km)
        except GeometryComputationError as error:
            return RegionResolution(
                state=RegionResolutionState.NEEDS_REGION,
                region=None,
                warnings=(str(error),),
                reason_code="invalid_point_region",
            )
        warnings = (
            (
                "Satellite acquisition footprints were ignored as geography; a tile "
                "center is not an event location.",
            )
            if any(
                item.source.source_kind is RegionSourceKind.ACQUISITION_FOOTPRINT
                for item in context.evidence
            )
            else ()
        )
        return self._resolved(
            context,
            core,
            source_footprints=(source,),
            association=AssociationStatus.CONFIRMED,
            margin_km=0,
            point_fallback=True,
            warnings=warnings,
        )

    def _combine_geometry(self, candidates: tuple[RegionEvidence, ...]) -> MultiPolygon:
        geometries = tuple(item.geometry for item in candidates)
        if any(geometry is None for geometry in geometries):
            raise GeometryComputationError("Selected region evidence has no geometry.")
        return self._geometry.union(
            tuple(geometry for geometry in geometries if geometry is not None)
        )

    @staticmethod
    def _user_evidence(
        context: IncidentImageryContext, geometry: MultiPolygon
    ) -> RegionEvidence:
        return RegionEvidence(
            evidence_id=f"user-region:{context.incident_id}:{geometry.sha256()[:12]}",
            geometry=geometry,
            source=RegionSource(
                source_id=f"user:{context.incident_id}",
                source_kind=RegionSourceKind.USER_SELECTED,
                publisher="Disaster Monitor operator",
                reference=context.incident_id,
            ),
            association=AssociationStatus.USER_SELECTED,
            semantic_role="user-selected inspection context",
        )

    def _validated_margin(self, value: float | None) -> float:
        margin = self._context_margin_km if value is None else value
        if not 0 <= margin <= 20:
            raise ValueError("The imagery context margin must be between 0 and 20 km.")
        return margin


def _region_id(
    incident_id: str, geometry: MultiPolygon, source_ids: tuple[str, ...]
) -> str:
    payload = "|".join((incident_id, geometry.sha256(), *source_ids))
    return f"region:{sha256(payload.encode('utf-8')).hexdigest()[:24]}"


RegionResolver = GroundImageryRegionResolver

__all__ = [
    "DEFAULT_CONTEXT_MARGIN_KM",
    "GroundImageryRegionResolver",
    "HAZARD_FALLBACK_RADII_KM",
    "IncidentImageryContext",
    "RegionResolution",
    "RegionResolutionState",
    "RegionResolver",
]
