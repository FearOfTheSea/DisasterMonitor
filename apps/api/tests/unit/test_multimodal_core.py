import base64
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from disaster_monitor.application.multimodal import (
    AssetAdmissionInput,
    VisualAnalysisRequest,
    VisualModelPrediction,
    VisualModelReadiness,
)
from disaster_monitor.application.services.common_operational_picture import (
    CommonOperationalPictureBuilder,
)
from disaster_monitor.application.services.event_resolution import (
    default_event_policy_registry,
)
from disaster_monitor.application.services.evidence_state import (
    build_evidence_world_state,
)
from disaster_monitor.application.services.multimodal_asset_admission import (
    MultimodalAssetAdmissionService,
)
from disaster_monitor.application.services.multimodal_association import (
    MultimodalEventAssociator,
)
from disaster_monitor.application.services.multimodal_state import (
    build_multimodal_evidence_state,
)
from disaster_monitor.application.services.visual_analysis import VisualAnalysisService
from disaster_monitor.domain.disaster import (
    Country,
    DisasterEvent,
    EventMeasurement,
    GeographicArea,
    Hazard,
    MeasurementKind,
    ReportedFact,
    SourceReference,
    point_event_geometry,
)
from disaster_monitor.domain.errors import MultimodalInputError
from disaster_monitor.domain.multimodal import (
    AnalyticalMapFeature,
    AnalyticalMapLayer,
    AssetEligibility,
    CaptureRole,
    CopStatus,
    DamageLevel,
    EventAssociationStatus,
    SourceGeometryAuthority,
    SourceMapFeature,
    SourceMapLayer,
    VisualAnalysisConfiguration,
    VisualObservationKind,
    VisualObservationStatus,
)
from disaster_monitor.presentation.http.multimodal_serialization import cop_response

NOW = datetime(2026, 8, 5, 12, tzinfo=UTC)
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
FOOTPRINT = (
    (
        (136.8, 34.8),
        (137.2, 34.8),
        (137.2, 35.2),
        (136.8, 35.2),
        (136.8, 34.8),
    ),
)


def _admission() -> MultimodalAssetAdmissionService:
    return MultimodalAssetAdmissionService(clock=lambda: NOW)


def _asset(**changes):
    values = {
        "content": PNG,
        "attribution": "Operator-provided xBD test crop",
        "captured_at": NOW + timedelta(hours=2),
        "footprint_coordinates": FOOTPRINT,
        "declared_hazard": Hazard.EARTHQUAKE,
        "declared_country_code": "JPN",
        "capture_role": CaptureRole.POST_EVENT,
        "dataset_id": "unit-fixture-v1",
        "license_name": "fixture-only",
        "processing_level": "raw",
    }
    values.update(changes)
    return _admission().admit(AssetAdmissionInput(**values))


def _physical_event(*, event_time: datetime = NOW):
    country = Country(
        "JPN",
        "Japan",
        (),
        GeographicArea(24, 46, 122, 146),
        "Asia/Tokyo",
    )
    source = SourceReference(
        "test-event-source",
        "Test scientific authority",
        "Event",
        "https://example.test/event",
        event_time,
        event_time,
        NOW,
    )
    event = DisasterEvent(
        "test:event-1",
        Hazard.EARTHQUAKE,
        "Central Japan",
        country,
        event_time,
        source,
        geometry=point_event_geometry(35.0, 137.0, source),
        measurements=(EventMeasurement(MeasurementKind.MAGNITUDE, 6.8, source=source),),
        provider_ids=("provider:event-1",),
    )
    return (
        default_event_policy_registry()
        .for_hazard(Hazard.EARTHQUAKE)
        .identify((event,))
        .physical_events[0]
    )


class FakeVisualAnalyzer:
    def __init__(
        self,
        *,
        answer: str | None = "a bridge is visibly damaged",
        damage_cues: tuple[str, ...] = ("collapsed roof",),
    ) -> None:
        self.answer = answer
        self.damage_cues = damage_cues
        self.requests: list[VisualAnalysisRequest] = []

    async def analyze(self, request: VisualAnalysisRequest) -> VisualModelPrediction:
        self.requests.append(request)
        return VisualModelPrediction(
            damage_level=DamageLevel.MAJOR_DAMAGE,
            damage_confidence=0.91,
            damage_cues=self.damage_cues,
            answer=self.answer if request.question is not None else None,
            answerable=request.question is not None,
            answer_confidence=0.84 if request.question is not None else None,
            answer_cues=("broken bridge deck",) if request.question is not None else (),
            configuration=_configuration(),
        )

    async def check_readiness(self) -> VisualModelReadiness:
        return VisualModelReadiness(
            True,
            True,
            "fake-vlm",
            "digest",
            "fake-adapter-v1",
            "dm-visual-analysis-v1",
            "original-png-jpeg-bytes-v1",
        )


def _configuration() -> VisualAnalysisConfiguration:
    return VisualAnalysisConfiguration(
        model_id="fake-vlm",
        model_digest="digest",
        adapter_version="fake-adapter-v1",
        analysis_version="analysis-v1",
        prompt_version="dm-visual-analysis-v1",
        preprocessing_version="original-png-jpeg-bytes-v1",
        maximum_output_tokens=384,
        temperature=0,
        seed=7,
    )


def test_asset_admission_derives_identity_and_preserves_unknown_metadata() -> None:
    asset = _asset(license_name=None, canonical_url=None)

    assert asset.eligibility == AssetEligibility.ANALYSIS_ELIGIBLE
    assert asset.media_type == "image/png"
    assert (asset.width, asset.height) == (1, 1)
    assert len(asset.content_sha256) == 64
    assert asset.source.canonical_url is None
    assert asset.source.license_name is None

    changed_metadata = _asset(captured_at=NOW + timedelta(hours=3))
    assert changed_metadata.content_sha256 == asset.content_sha256
    assert changed_metadata.asset_id != asset.asset_id
    changed_source = _asset(dataset_id="different-dataset-v2")
    assert changed_source.content_sha256 == asset.content_sha256
    assert changed_source.asset_id != asset.asset_id

    contradictory = _asset(parent_asset_ids=(asset.asset_id,))
    assert contradictory.eligibility == AssetEligibility.REJECTED
    assert "raw_asset_has_parent_lineage" in contradictory.eligibility_reasons


def test_missing_or_malformed_asset_metadata_cannot_become_analysis_eligible() -> None:
    orphan = _asset(captured_at=None, footprint_coordinates=None)
    assert orphan.eligibility == AssetEligibility.ORPHANED
    assert set(orphan.eligibility_reasons) >= {
        "missing_capture_time",
        "missing_georeference",
    }

    swapped = _asset(
        footprint_coordinates=(
            ((35.0, 137.0), (35.1, 137.0), (35.1, 137.1), (35.0, 137.0)),
        )
    )
    assert swapped.eligibility == AssetEligibility.REJECTED
    assert "invalid_georeference" in swapped.eligibility_reasons

    with pytest.raises(MultimodalInputError, match="PNG|JPEG"):
        _admission().admit(AssetAdmissionInput(b"not-an-image", "Test source"))

    outside_hole = _asset(
        footprint_coordinates=(
            FOOTPRINT[0],
            (
                (140.0, 40.0),
                (140.1, 40.0),
                (140.1, 40.1),
                (140.0, 40.0),
            ),
        )
    )
    assert outside_hole.eligibility == AssetEligibility.REJECTED
    assert "invalid_georeference" in outside_hole.eligibility_reasons


@pytest.mark.parametrize(
    ("asset", "expected"),
    (
        (_asset(), EventAssociationStatus.ASSOCIATED),
        (
            replace(_asset(), declared_country_code="VNM"),
            EventAssociationStatus.UNMATCHED,
        ),
        (
            replace(_asset(), declared_hazard=Hazard.FLOOD),
            EventAssociationStatus.UNMATCHED,
        ),
        (
            replace(_asset(), captured_at=NOW - timedelta(hours=2)),
            EventAssociationStatus.UNMATCHED,
        ),
        (
            replace(_asset(), captured_at=NOW + timedelta(days=31)),
            EventAssociationStatus.UNMATCHED,
        ),
        (
            replace(_asset(), event_id_hint="another:event"),
            EventAssociationStatus.UNMATCHED,
        ),
        (
            replace(
                _asset(),
                captured_at=None,
                eligibility=AssetEligibility.ORPHANED,
                eligibility_reasons=("missing_capture_time",),
            ),
            EventAssociationStatus.ORPHANED,
        ),
    ),
)
def test_geotemporal_association_uses_metadata_not_pixels(asset, expected) -> None:
    result = MultimodalEventAssociator().associate(asset, _physical_event())

    assert result.status == expected
    assert result.asset_id == asset.asset_id
    assert result.physical_event_id == _physical_event().physical_event_id


def test_near_boundary_is_ambiguous_and_material_offset_is_unmatched() -> None:
    near = _asset(
        footprint_coordinates=(
            (
                (137.05, 34.8),
                (137.2, 34.8),
                (137.2, 35.2),
                (137.05, 35.2),
                (137.05, 34.8),
            ),
        )
    )
    far = _asset(
        footprint_coordinates=(
            (
                (138.0, 35.8),
                (138.2, 35.8),
                (138.2, 36.0),
                (138.0, 36.0),
                (138.0, 35.8),
            ),
        )
    )

    associator = MultimodalEventAssociator()
    assert associator.associate(near, _physical_event()).status == "ambiguous"
    assert associator.associate(far, _physical_event()).status == "unmatched"


@pytest.mark.asyncio
async def test_visual_safety_abstains_from_casualty_questions_before_model() -> None:
    analyzer = FakeVisualAnalyzer()
    asset = _asset()
    association = MultimodalEventAssociator().associate(asset, _physical_event())
    service = VisualAnalysisService(analyzer, clock=lambda: NOW)

    observations = await service.analyze(
        asset,
        association,
        question="How many people were killed in this image?",
    )

    assert analyzer.requests[0].question is None
    assert observations[0].kind == VisualObservationKind.DAMAGE_ASSESSMENT
    assert observations[0].truth_status == "analytical"
    assert not isinstance(observations[0], ReportedFact)
    answer = observations[1]
    assert answer.status == VisualObservationStatus.ABSTAINED
    assert answer.answer is None
    assert answer.safety_rule_ids == ("mm.visual.prohibited_question",)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question",
    (
        "What is the name of the person?",
        "Is an evacuation advisory active?",
        "What government decision was made?",
        "Is an official warning in effect?",
    ),
)
async def test_visual_safety_blocks_other_unauthorized_claim_classes_before_model(
    question: str,
) -> None:
    analyzer = FakeVisualAnalyzer()
    asset = _asset()
    association = MultimodalEventAssociator().associate(asset, _physical_event())

    observations = await VisualAnalysisService(analyzer, clock=lambda: NOW).analyze(
        asset, association, question=question
    )

    assert analyzer.requests[0].question is None
    assert observations[1].status == VisualObservationStatus.ABSTAINED
    assert observations[1].answer is None
    assert observations[1].safety_rule_ids == ("mm.visual.prohibited_question",)


@pytest.mark.asyncio
async def test_visual_safety_blocks_an_unsafe_numeric_model_answer() -> None:
    analyzer = FakeVisualAnalyzer(answer="12 people were killed")
    asset = _asset()
    association = MultimodalEventAssociator().associate(asset, _physical_event())

    observations = await VisualAnalysisService(analyzer, clock=lambda: NOW).analyze(
        asset,
        association,
        question="What visible impact is present?",
    )

    answer = observations[1]
    assert observations[0].status == VisualObservationStatus.ABSTAINED
    assert observations[0].damage_level == DamageLevel.UNKNOWN
    assert answer.status == VisualObservationStatus.ABSTAINED
    assert answer.answer is None
    assert answer.safety_rule_ids == ("mm.visual.unsafe_output_blocked",)


@pytest.mark.asyncio
async def test_visual_safety_discards_unsafe_model_cues() -> None:
    analyzer = FakeVisualAnalyzer(damage_cues=("12 people were killed",))
    asset = _asset()
    association = MultimodalEventAssociator().associate(asset, _physical_event())

    observations = await VisualAnalysisService(analyzer, clock=lambda: NOW).analyze(
        asset, association, question=None
    )

    damage = observations[0]
    assert damage.status == VisualObservationStatus.ABSTAINED
    assert damage.damage_level == DamageLevel.UNKNOWN
    assert damage.visual_cues == ()
    assert damage.safety_rule_ids == ("mm.visual.unsafe_output_blocked",)


@pytest.mark.asyncio
async def test_multimodal_state_and_cop_preserve_ew_and_geometry_lineage() -> None:
    analyzer = FakeVisualAnalyzer()
    asset = _asset()
    physical_event = _physical_event()
    association = MultimodalEventAssociator().associate(asset, physical_event)
    observations = await VisualAnalysisService(analyzer, clock=lambda: NOW).analyze(
        asset,
        association,
        question=None,
    )
    ew_state = build_evidence_world_state(
        physical_event.event,
        (),
        evaluated_at=NOW,
        physical_event=physical_event,
    )
    state = build_multimodal_evidence_state(
        ew_state,
        (asset,),
        (association,),
        observations,
        evaluated_at=NOW,
    )

    cop = CommonOperationalPictureBuilder().build(state, created_at=NOW)

    assert state.evidence_world_state_version == ew_state.state_version
    assert cop is not None
    assert cop.multimodal_state_version == state.state_version
    layer = cop.layers[0]
    assert isinstance(layer, AnalyticalMapLayer)
    feature = layer.features[0]
    assert feature.authority == "analytical_generated"
    assert feature.source_asset_ids == (asset.asset_id,)
    assert feature.visual_observation_ids == (observations[0].observation_id,)
    assert feature.uncertainty
    assert layer.source_asset_ids == (asset.asset_id,)
    assert layer.visual_observation_ids == (observations[0].observation_id,)
    assert layer.status == CopStatus.CURRENT
    assert layer.uncertainty
    with pytest.raises(ValueError, match="asset lineage"):
        replace(layer, source_asset_ids=("asset:wrong",))

    changed = build_multimodal_evidence_state(
        ew_state,
        (asset,),
        (association,),
        (replace(observations[0], confidence=0.5),),
        evaluated_at=NOW,
    )
    assert changed.state_version != state.state_version


@pytest.mark.asyncio
async def test_official_and_analytical_map_features_are_structurally_separate() -> None:
    asset = _asset()
    physical_event = _physical_event()
    association = MultimodalEventAssociator().associate(asset, physical_event)
    observations = await VisualAnalysisService(
        FakeVisualAnalyzer(), clock=lambda: NOW
    ).analyze(asset, association, question=None)
    ew_state = build_evidence_world_state(
        physical_event.event, (), evaluated_at=NOW, physical_event=physical_event
    )
    state = build_multimodal_evidence_state(
        ew_state, (asset,), (association,), observations, evaluated_at=NOW
    )
    official = SourceMapFeature(
        feature_id="official:1",
        physical_event_id=physical_event.physical_event_id,
        source_id="official-warning-source",
        source_asset_ids=(asset.asset_id,),
        created_at=NOW,
        updated_at=None,
        semantic_kind="warning_boundary",
        geometry=asset.footprint,
        attribution="Official source fixture",
        status=CopStatus.CURRENT,
        uncertainty="Source status as published.",
        source_authority=SourceGeometryAuthority.OFFICIAL,
    )

    cop = CommonOperationalPictureBuilder().build(
        state, created_at=NOW, source_features=(official,)
    )

    assert cop is not None
    assert isinstance(cop.layers[0], SourceMapLayer)
    assert isinstance(cop.layers[0].features[0], SourceMapFeature)
    assert cop.layers[0].features[0].authority == "official_source"
    assert isinstance(cop.layers[1].features[0], AnalyticalMapFeature)
    serialized = cop_response(cop)
    assert serialized is not None
    assert serialized.layers[0].layer_type == "source"
    assert serialized.layers[0].source_asset_ids == [asset.asset_id]
    assert serialized.layers[0].features[0].authority == "official_source"
    assert serialized.layers[1].layer_type == "analytical"
    assert serialized.layers[1].features[0].authority == "analytical_generated"
    with pytest.raises(TypeError, match="authority"):
        AnalyticalMapFeature(
            feature_id="unsafe",
            physical_event_id=physical_event.physical_event_id,
            source_asset_ids=(asset.asset_id,),
            visual_observation_ids=(observations[0].observation_id,),
            created_at=NOW,
            updated_at=None,
            semantic_kind="warning_boundary",
            geometry=asset.footprint,
            attribution="Unsafe",
            status=CopStatus.CURRENT,
            uncertainty="Unsafe",
            confidence=1,
            authority="official_source",
        )
