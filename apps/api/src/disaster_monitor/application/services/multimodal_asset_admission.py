"""Bounded admission of genuine operator-supplied image assets."""

from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256

from disaster_monitor.application.multimodal import AssetAdmissionInput
from disaster_monitor.application.ports.image_metadata import image_metadata
from disaster_monitor.application.services.multimodal_geometry import (
    MultimodalGeometryPolicy,
)
from disaster_monitor.domain.errors import MultimodalInputError
from disaster_monitor.domain.multimodal import (
    AssetEligibility,
    AssetModality,
    CaptureRole,
    MultimodalAsset,
    MultimodalSourceMetadata,
)

MAX_ASSET_BYTES = 5_000_000
MAX_ASSETS_PER_REQUEST = 3
OPERATOR_ASSET_SOURCE_ID = "operator-supplied-multimodal"


class MultimodalAssetAdmissionService:
    """Derive immutable identity while preserving unknown source metadata."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime],
        geometry_policy: MultimodalGeometryPolicy | None = None,
        max_asset_bytes: int = MAX_ASSET_BYTES,
    ) -> None:
        self._clock = clock
        self._geometry = geometry_policy or MultimodalGeometryPolicy()
        self._max_asset_bytes = max_asset_bytes

    def admit_many(
        self, inputs: tuple[AssetAdmissionInput, ...]
    ) -> tuple[MultimodalAsset, ...]:
        if len(inputs) > MAX_ASSETS_PER_REQUEST:
            raise MultimodalInputError(
                f"At most {MAX_ASSETS_PER_REQUEST} multimodal assets are accepted."
            )
        assets = tuple(self.admit(item) for item in inputs)
        known = {asset.asset_id for asset in assets}
        for asset in assets:
            missing_parents = set(asset.parent_asset_ids) - known
            if missing_parents:
                raise MultimodalInputError(
                    "Derived asset parent IDs must refer to assets in the same request."
                )
        return assets

    def admit(self, item: AssetAdmissionInput) -> MultimodalAsset:
        if not item.content:
            raise MultimodalInputError("A multimodal asset cannot be empty.")
        if len(item.content) > self._max_asset_bytes:
            raise MultimodalInputError(
                f"A multimodal asset cannot exceed {self._max_asset_bytes} bytes."
            )
        attribution = item.attribution.strip()
        if not attribution:
            raise MultimodalInputError("Asset source attribution is required.")
        try:
            media_type, width, height = image_metadata(item.content)
        except ValueError as error:
            raise MultimodalInputError(str(error)) from error

        reasons: list[str] = []
        footprint = None
        rejected = False
        if item.footprint_coordinates is None:
            reasons.append("missing_georeference")
        else:
            try:
                footprint = self._geometry.polygon(
                    item.footprint_coordinates, crs=item.footprint_crs
                )
            except ValueError:
                reasons.append("invalid_georeference")
                rejected = True

        captured_at = item.captured_at
        if captured_at is None:
            reasons.append("missing_capture_time")
        elif captured_at.tzinfo is None:
            reasons.append("capture_time_requires_timezone")
            rejected = True
        if item.declared_disaster is None:
            reasons.append("missing_declared_disaster")
        country_code = (item.declared_country_code or "").strip().upper() or None
        if country_code is None:
            reasons.append("missing_declared_country")
        elif len(country_code) != 3 or not country_code.isalpha():
            reasons.append("invalid_declared_country")
            rejected = True
        if item.capture_role == CaptureRole.UNKNOWN:
            reasons.append("unknown_capture_role")
        if item.parent_asset_ids and not (item.processing_level or "").strip():
            reasons.append("derived_asset_missing_processing_level")
        if (
            item.parent_asset_ids
            and (item.processing_level or "").strip().casefold() == "raw"
        ):
            reasons.append("raw_asset_has_parent_lineage")
            rejected = True
        if item.processing_level and item.processing_level.strip().casefold() != "raw":
            if not item.parent_asset_ids:
                reasons.append("derived_asset_missing_parent_lineage")

        try:
            source = MultimodalSourceMetadata(
                source_id=OPERATOR_ASSET_SOURCE_ID,
                attribution=attribution,
                canonical_url=item.canonical_url,
                dataset_id=item.dataset_id,
                license_name=item.license_name,
            )
        except ValueError as error:
            raise MultimodalInputError(str(error)) from error

        orphan_reasons = {
            "missing_georeference",
            "missing_capture_time",
            "missing_declared_disaster",
            "missing_declared_country",
            "derived_asset_missing_processing_level",
            "derived_asset_missing_parent_lineage",
        }
        if rejected:
            eligibility = AssetEligibility.REJECTED
        elif orphan_reasons.intersection(reasons):
            eligibility = AssetEligibility.ORPHANED
        elif reasons:
            eligibility = AssetEligibility.PREVIEW_ONLY
        else:
            eligibility = AssetEligibility.ANALYSIS_ELIGIBLE

        checksum = sha256(item.content).hexdigest()
        captured_material = (
            captured_at.isoformat() if captured_at is not None else "unknown"
        )
        footprint_material = (
            "unknown"
            if footprint is None
            else ";".join(
                ",".join(f"{point.longitude}:{point.latitude}" for point in ring)
                for ring in footprint.rings
            )
        )
        identity_material = "|".join(
            (
                OPERATOR_ASSET_SOURCE_ID,
                checksum,
                source.attribution,
                source.canonical_url or "",
                source.dataset_id or "",
                source.license_name or "",
                captured_material,
                item.declared_disaster.value if item.declared_disaster else "unknown",
                country_code or "unknown",
                item.capture_role.value,
                footprint_material,
                item.event_id_hint or "",
                item.processing_level or "",
                *item.parent_asset_ids,
            )
        )
        asset_id = f"asset:{sha256(identity_material.encode('utf-8')).hexdigest()[:24]}"
        retrieved_at = self._clock()
        if retrieved_at.tzinfo is None:
            retrieved_at = retrieved_at.replace(tzinfo=UTC)
        return MultimodalAsset(
            asset_id=asset_id,
            source=source,
            retrieved_at=retrieved_at,
            captured_at=captured_at,
            modality=AssetModality.IMAGE,
            media_type=media_type,
            content_sha256=checksum,
            byte_length=len(item.content),
            width=width,
            height=height,
            footprint=footprint,
            declared_disaster=item.declared_disaster,
            declared_country_code=country_code,
            capture_role=item.capture_role,
            processing_level=item.processing_level,
            parent_asset_ids=item.parent_asset_ids,
            event_id_hint=item.event_id_hint,
            eligibility=eligibility,
            eligibility_reasons=tuple(reasons),
            content=item.content,
        )
