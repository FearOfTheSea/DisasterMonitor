import hashlib
from datetime import UTC, datetime

from disaster_monitor.domain.disaster import EvidenceWorldState
from disaster_monitor.domain.multimodal import (
    AssetEligibility,
    AssetModality,
    CaptureRole,
    MultimodalAsset,
    MultimodalEvidenceState,
    MultimodalSourceMetadata,
)

COORDINATION_NOW = datetime(2026, 8, 11, 12, tzinfo=UTC)


def build_multimodal_state(
    state: EvidenceWorldState, case_id: str
) -> MultimodalEvidenceState:
    content = b"frozen-co-b-asset"
    asset = MultimodalAsset(
        asset_id=f"asset:{case_id}",
        source=MultimodalSourceMetadata(
            source_id=f"operator-asset:{case_id}",
            attribution="Frozen CO-B operator asset",
        ),
        retrieved_at=COORDINATION_NOW,
        captured_at=COORDINATION_NOW,
        modality=AssetModality.IMAGE,
        media_type="image/png",
        content_sha256=hashlib.sha256(content).hexdigest(),
        byte_length=len(content),
        width=1,
        height=1,
        footprint=None,
        declared_disaster=state.physical_event.event.disaster,
        declared_country_code=state.physical_event.event.country.alpha3_code,
        capture_role=CaptureRole.SINGLE_CAPTURE,
        processing_level="raw",
        parent_asset_ids=(),
        event_id_hint=state.physical_event.event.event_id,
        eligibility=AssetEligibility.ANALYSIS_ELIGIBLE,
        eligibility_reasons=("frozen-co-b",),
        content=content,
    )
    return MultimodalEvidenceState(
        state_version=f"multimodal:{case_id}",
        evidence_world_state_version=state.state_version,
        physical_event_id=state.physical_event.physical_event_id,
        assets=(asset,),
        associations=(),
        observations=(),
        evaluated_at=COORDINATION_NOW,
    )
