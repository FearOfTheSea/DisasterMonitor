"""Metadata-owned geotemporal association with PhysicalEventIdentity."""

from dataclasses import dataclass
from datetime import timedelta
from hashlib import sha256

from disaster_monitor.application.services.multimodal_geometry import (
    MultimodalGeometryPolicy,
)
from disaster_monitor.domain.disaster import PhysicalEventIdentity
from disaster_monitor.domain.multimodal import (
    AssetEligibility,
    AssetEventAssociation,
    CaptureRole,
    EventAssociationStatus,
    GeoPoint,
    MultimodalAsset,
)


@dataclass(frozen=True, slots=True)
class GeotemporalAssociationPolicy:
    """One centralized set of conservative MM-B matching thresholds."""

    boundary_tolerance_km: float = 25.0
    single_capture_window: timedelta = timedelta(days=7)
    maximum_post_event_age: timedelta = timedelta(days=30)
    maximum_pre_event_age: timedelta = timedelta(days=365)


class MultimodalEventAssociator:
    """Associate explicit metadata; never use pixels or model speculation."""

    def __init__(
        self,
        *,
        policy: GeotemporalAssociationPolicy | None = None,
        geometry_policy: MultimodalGeometryPolicy | None = None,
    ) -> None:
        self.policy = policy or GeotemporalAssociationPolicy()
        self._geometry = geometry_policy or MultimodalGeometryPolicy()

    def associate(
        self, asset: MultimodalAsset, physical_event: PhysicalEventIdentity
    ) -> AssetEventAssociation:
        event = physical_event.event
        rules: list[str] = []
        if asset.eligibility != AssetEligibility.ANALYSIS_ELIGIBLE:
            return self._result(
                asset,
                physical_event,
                EventAssociationStatus.ORPHANED,
                geography=None,
                time=None,
                hazard=None,
                country=None,
                event_id=None,
                distance=None,
                time_delta=None,
                rules=("mm.association.asset_not_eligible",),
                detail="Asset metadata is incomplete or invalid for event association.",
            )
        if asset.footprint is None or asset.captured_at is None:
            return self._result(
                asset,
                physical_event,
                EventAssociationStatus.ORPHANED,
                geography=None,
                time=None,
                hazard=None,
                country=None,
                event_id=None,
                distance=None,
                time_delta=None,
                rules=("mm.association.required_metadata_missing",),
                detail="Capture time and georeference are required.",
            )
        if event.latitude is None or event.longitude is None:
            return self._result(
                asset,
                physical_event,
                EventAssociationStatus.ORPHANED,
                geography=None,
                time=None,
                hazard=None,
                country=None,
                event_id=None,
                distance=None,
                time_delta=None,
                rules=("mm.association.event_georeference_missing",),
                detail="The selected physical event lacks point georeference.",
            )

        hazard_match = asset.declared_hazard == event.hazard
        country_match = asset.declared_country_code == event.country.alpha3_code
        rules.extend(("mm.association.hazard_exact", "mm.association.country_exact"))
        event_identifiers = {
            physical_event.physical_event_id.casefold(),
            event.event_id.casefold(),
            *(identifier.casefold() for identifier in event.provider_ids),
        }
        event_id_match = (
            None
            if asset.event_id_hint is None
            else asset.event_id_hint.casefold() in event_identifiers
        )
        if asset.event_id_hint is not None:
            rules.append("mm.association.event_identifier_exact")

        event_point = GeoPoint(event.longitude, event.latitude)
        distance = self._geometry.distance_to_polygon_km(asset.footprint, event_point)
        geography_match = distance == 0
        near_boundary = 0 < distance <= self.policy.boundary_tolerance_km
        rules.append("mm.association.wgs84_footprint_distance")

        delta = asset.captured_at - event.event_time
        time_delta = delta.total_seconds()
        time_match = self._time_matches(asset.capture_role, delta)
        rules.append(f"mm.association.capture_role.{asset.capture_role.value}")

        mismatched = (
            not hazard_match
            or not country_match
            or event_id_match is False
            or not time_match
            or (not geography_match and not near_boundary)
        )
        if mismatched:
            status = EventAssociationStatus.UNMATCHED
            detail = (
                "Trusted hazard, country, event, time, or footprint metadata "
                "mismatched."
            )
        elif near_boundary:
            status = EventAssociationStatus.AMBIGUOUS
            detail = "The event is near, but outside, the supplied footprint boundary."
        else:
            status = EventAssociationStatus.ASSOCIATED
            detail = (
                "Explicit hazard, country, capture time, and footprint metadata match."
            )
        return self._result(
            asset,
            physical_event,
            status,
            geography=geography_match,
            time=time_match,
            hazard=hazard_match,
            country=country_match,
            event_id=event_id_match,
            distance=distance,
            time_delta=time_delta,
            rules=tuple(rules),
            detail=detail,
        )

    def _time_matches(self, role: CaptureRole, delta: timedelta) -> bool:
        if role == CaptureRole.PRE_EVENT:
            return -self.policy.maximum_pre_event_age <= delta <= timedelta(0)
        if role == CaptureRole.POST_EVENT:
            return timedelta(0) <= delta <= self.policy.maximum_post_event_age
        if role == CaptureRole.SINGLE_CAPTURE:
            return abs(delta) <= self.policy.single_capture_window
        return False

    @staticmethod
    def _result(
        asset: MultimodalAsset,
        physical_event: PhysicalEventIdentity,
        status: EventAssociationStatus,
        *,
        geography: bool | None,
        time: bool | None,
        hazard: bool | None,
        country: bool | None,
        event_id: bool | None,
        distance: float | None,
        time_delta: float | None,
        rules: tuple[str, ...],
        detail: str,
    ) -> AssetEventAssociation:
        material = "|".join(
            (
                asset.asset_id,
                physical_event.physical_event_id,
                status.value,
                *(rules),
            )
        )
        return AssetEventAssociation(
            association_id=(
                f"asset-event:{sha256(material.encode('utf-8')).hexdigest()[:24]}"
            ),
            asset_id=asset.asset_id,
            physical_event_id=physical_event.physical_event_id,
            status=status,
            geography_match=geography,
            time_match=time,
            hazard_match=hazard,
            country_match=country,
            event_id_match=event_id,
            distance_km=distance,
            time_delta_seconds=time_delta,
            rule_ids=rules,
            detail=detail,
        )
