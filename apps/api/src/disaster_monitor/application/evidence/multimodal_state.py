"""Version multimodal analytical state against the canonical EW version."""

from datetime import UTC, datetime
from hashlib import sha256

from disaster_monitor.domain.disaster import EvidenceWorldState
from disaster_monitor.domain.multimodal import (
    AssetEventAssociation,
    MultimodalAsset,
    MultimodalEvidenceState,
    VisualObservation,
)


def build_multimodal_evidence_state(
    evidence_state: EvidenceWorldState,
    assets: tuple[MultimodalAsset, ...],
    associations: tuple[AssetEventAssociation, ...],
    observations: tuple[VisualObservation, ...],
    *,
    evaluated_at: datetime,
) -> MultimodalEvidenceState:
    """Build an order-independent version that changes on analytical changes."""
    evaluated = (
        evaluated_at
        if evaluated_at.tzinfo is not None
        else evaluated_at.replace(tzinfo=UTC)
    )
    ordered_assets = tuple(sorted(assets, key=lambda item: item.asset_id))
    ordered_associations = tuple(
        sorted(associations, key=lambda item: item.association_id)
    )
    ordered_observations = tuple(
        sorted(observations, key=lambda item: item.observation_id)
    )
    material = "|".join(
        (
            evidence_state.state_version,
            evidence_state.physical_event.physical_event_id,
            *(
                f"asset:{item.asset_id}:{item.content_sha256}:{item.eligibility.value}"
                for item in ordered_assets
            ),
            *(
                f"association:{item.association_id}:{item.status.value}:"
                f"{item.distance_km}:{item.time_delta_seconds}"
                for item in ordered_associations
            ),
            *(
                f"observation:{item.observation_id}:{item.status.value}:"
                f"{item.damage_level}:{item.answer}:{item.confidence}:"
                f"{item.configuration.analysis_version}"
                for item in ordered_observations
            ),
        )
    )
    return MultimodalEvidenceState(
        state_version=(
            f"multimodal-state:{sha256(material.encode('utf-8')).hexdigest()[:24]}"
        ),
        evidence_world_state_version=evidence_state.state_version,
        physical_event_id=evidence_state.physical_event.physical_event_id,
        assets=ordered_assets,
        associations=ordered_associations,
        observations=ordered_observations,
        evaluated_at=evaluated,
    )
