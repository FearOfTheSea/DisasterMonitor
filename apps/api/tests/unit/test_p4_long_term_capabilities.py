import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from disaster_monitor.application.ground_imagery.micro_review import (
    summarize_micro_reviews,
)
from disaster_monitor.application.historical_loss.context import (
    HistoricalLossContextService,
)
from disaster_monitor.application.localization.terminology import TerminologyResolver
from disaster_monitor.application.operator_workspace.service import (
    OperatorWorkspaceService,
)
from disaster_monitor.application.planning.service import PlanningWorkspaceService
from disaster_monitor.application.social_signals.lane import OpenSocialSignalLane
from disaster_monitor.application.social_signals.triage import (
    LocalSignalTriageClassifier,
)
from disaster_monitor.domain.disaster_types import Disaster
from disaster_monitor.domain.historical_loss import HistoricalLossRecord
from disaster_monitor.domain.imagery.analysis import (
    AnalyticalFindingReview,
    AnalyticalImageryFinding,
    FindingReviewDecision,
)
from disaster_monitor.domain.news import NewsFeedItem
from disaster_monitor.domain.operator_workspace import NotebookEntryKind
from disaster_monitor.domain.planning import (
    PlanningLayer,
    WorkspaceKind,
    WorkspaceTarget,
)
from disaster_monitor.domain.social_signals import (
    OperatorSignalLabel,
    SignalCategory,
    SignalSourceTerms,
    UntrustedSocialSignal,
)
from disaster_monitor.infrastructure.localization.json_terminology import (
    JsonTerminologyPackReader,
)
from disaster_monitor.infrastructure.operator_workspace.json_store import (
    JsonOperatorWorkspaceStore,
)
from disaster_monitor.infrastructure.planning.memory_store import (
    InMemoryPlanningWorkspaceStore,
)

NOW = datetime(2026, 9, 22, 8, tzinfo=UTC)
REPOSITORY_ROOT = Path(__file__).resolve().parents[4]


def _signal(*, signal_id: str, text: str) -> UntrustedSocialSignal:
    return UntrustedSocialSignal(
        signal_id=signal_id,
        source_id="public-mastodon-example",
        external_id=signal_id.removeprefix("signal:"),
        text=text,
        canonical_url=f"https://social.example/@observer/{signal_id[-1]}",
        published_at=NOW - timedelta(minutes=10),
        retrieved_at=NOW,
        source_terms=SignalSourceTerms(
            source_id="public-mastodon-example",
            access_model="public",
            terms_url="https://social.example/terms",
            reviewed_at=NOW - timedelta(days=30),
            redistribution_permitted=False,
        ),
    )


def test_social_signal_classification_never_changes_source_authority() -> None:
    training = (
        OperatorSignalLabel.create(
            signal=_signal(
                signal_id="signal:training-1",
                text="Bridge approach is covered by flood water",
            ),
            reviewer_id="operator:alice",
            category=SignalCategory.INFRASTRUCTURE_DISRUPTION,
            labelled_at=NOW,
        ),
        OperatorSignalLabel.create(
            signal=_signal(
                signal_id="signal:training-2",
                text="Weekly community meeting starts tonight",
            ),
            reviewer_id="operator:alice",
            category=SignalCategory.NOT_RELEVANT,
            labelled_at=NOW,
        ),
    )
    signal = _signal(
        signal_id="signal:candidate-1",
        text="Flood water is covering the bridge approach",
    )

    result = LocalSignalTriageClassifier(
        model_id="operator-labelled-token-overlap",
        model_version="1.0.0",
    ).classify(signal, training)

    assert result.category is SignalCategory.INFRASTRUCTURE_DISRUPTION
    assert result.training_label_ids == tuple(item.label_id for item in training)
    assert result.discovery_candidate is True
    assert result.authority == "untrusted_signal"
    assert result.authority_changed is False
    assert signal.creates_physical_event is False


def test_social_signal_requires_reviewed_public_terms_and_https_lineage() -> None:
    with pytest.raises(ValueError, match="public or self-hosted"):
        SignalSourceTerms(
            source_id="paid-firehose",
            access_model="paid",
            terms_url="https://example.test/terms",
            reviewed_at=NOW,
            redistribution_permitted=False,
        )


@pytest.mark.asyncio
async def test_open_feed_lane_admits_discovery_candidates_only() -> None:
    class PublicFeed:
        source_id = "public-mastodon-example"

        async def fetch_since(self, *, since: datetime, now: datetime):
            assert since == NOW - timedelta(hours=1)
            assert now == NOW
            return (
                NewsFeedItem(
                    external_id="post-42",
                    publisher="Public community feed",
                    title="Possible flooding beside the old bridge",
                    canonical_url="https://social.example/@observer/42",
                    published_at=NOW - timedelta(minutes=10),
                    updated_at=None,
                ),
            )

    terms = SignalSourceTerms(
        source_id="public-mastodon-example",
        access_model="public",
        terms_url="https://social.example/terms",
        reviewed_at=NOW - timedelta(days=30),
        redistribution_permitted=False,
    )

    signals = await OpenSocialSignalLane(PublicFeed(), terms).fetch_since(
        since=NOW - timedelta(hours=1), now=NOW
    )

    assert len(signals) == 1
    assert signals[0].authority == "untrusted_signal"
    assert signals[0].creates_physical_event is False
    assert signals[0].text == "Possible flooding beside the old bridge"

    with pytest.raises(ValueError, match="HTTPS"):
        _signal(signal_id="signal:bad", text="Possible flood").__class__(
            signal_id="signal:bad",
            source_id="public-mastodon-example",
            external_id="bad",
            text="Possible flood",
            canonical_url="http://social.example/post/bad",
            published_at=NOW,
            retrieved_at=NOW,
            source_terms=SignalSourceTerms(
                source_id="public-mastodon-example",
                access_model="public",
                terms_url="https://social.example/terms",
                reviewed_at=NOW,
                redistribution_permitted=False,
            ),
        )


def test_micro_review_supports_only_analytical_confidence() -> None:
    finding = AnalyticalImageryFinding(
        finding_id="finding:flood-change",
        algorithm_id="sentinel-1-flood-change",
        algorithm_version="1.0.0",
        source_product_ids=("before", "after"),
        metrics={"changed_fraction": 0.42},
        threshold_parameters=(("ratio", 0.35),),
        interpretation="Possible analytical flood-related change.",
    )
    reviews = tuple(
        AnalyticalFindingReview.create(
            finding=finding,
            decision=decision,
            reviewer_id=f"operator:{index}",
            reviewed_at=NOW + timedelta(minutes=index),
        )
        for index, decision in enumerate(
            (
                FindingReviewDecision.ACCEPTED,
                FindingReviewDecision.ACCEPTED,
                FindingReviewDecision.NEEDS_FOLLOW_UP,
            ),
            start=1,
        )
    )

    summary = summarize_micro_reviews(finding, reviews, minimum_reviewers=2)

    assert summary.independent_reviewer_count == 3
    assert summary.accepted_fraction == pytest.approx(2 / 3)
    assert summary.supports_analytical_confidence is True
    assert summary.official_damage_claim is False
    assert summary.evidence_role == "analytical_observation"


@pytest.mark.asyncio
async def test_scenario_and_replay_workspaces_cannot_target_live_evidence() -> None:
    service = PlanningWorkspaceService(
        InMemoryPlanningWorkspaceStore(), clock=lambda: NOW
    )
    scenario = await service.create_scenario(
        title="River flood preparedness exercise",
        created_by="operator:alice",
        source_snapshot_ids=("snapshot:baseline",),
        assumptions=("The river rises one metre above the observed gauge value.",),
        layers=(
            PlanningLayer(
                layer_id="scenario-layer:depth",
                title="Hypothetical depth",
                source_reference="operator-supplied-scenario.geojson",
                sha256="a" * 64,
            ),
        ),
    )
    replay = await service.create_replay(
        title="Historical earthquake replay",
        created_by="operator:alice",
        source_snapshot_ids=("snapshot:historical-event",),
        replay_started_at=NOW - timedelta(hours=2),
    )

    assert scenario.kind is WorkspaceKind.PLANNING_SCENARIO
    assert replay.kind is WorkspaceKind.HISTORICAL_REPLAY
    assert scenario.simulated is True
    assert replay.simulated is True
    with pytest.raises(ValueError, match="canonical evidence"):
        await service.assert_write_allowed(
            scenario.workspace_id, WorkspaceTarget.CANONICAL_EVIDENCE
        )
    with pytest.raises(ValueError, match="canonical evidence"):
        await service.assert_write_allowed(
            replay.workspace_id, WorkspaceTarget.CANONICAL_EVIDENCE
        )


class _HistoricalLossProvider:
    source_id = "desinventar-reviewed-export"

    async def records(
        self, *, country_code: str, hazard: Disaster
    ) -> tuple[HistoricalLossRecord, ...]:
        assert country_code == "VNM"
        assert hazard is Disaster.FLOOD
        return (
            HistoricalLossRecord(
                record_id="desinventar:1999-01",
                dataset_id="desinventar-vnm-2025",
                source_id=self.source_id,
                country_code="VNM",
                hazard=Disaster.FLOOD,
                event_name="1999 river flood",
                occurred_at=datetime(1999, 11, 1, tzinfo=UTC),
                fatalities=12,
                people_affected=50_000,
                economic_loss_usd=None,
                source_url="https://www.desinventar.net/database",
                license_name="reviewed dataset terms",
                dataset_updated_at=datetime(2025, 1, 1, tzinfo=UTC),
                retrieved_at=NOW,
            ),
            HistoricalLossRecord(
                record_id="desinventar:future",
                dataset_id="desinventar-vnm-2025",
                source_id=self.source_id,
                country_code="VNM",
                hazard=Disaster.FLOOD,
                event_name="Bad future record",
                occurred_at=NOW + timedelta(days=1),
                fatalities=1,
                people_affected=None,
                economic_loss_usd=None,
                source_url="https://www.desinventar.net/database",
                license_name="reviewed dataset terms",
                dataset_updated_at=datetime(2025, 1, 1, tzinfo=UTC),
                retrieved_at=NOW,
            ),
        )


@pytest.mark.asyncio
async def test_historical_loss_context_cannot_infer_current_impact() -> None:
    context = await HistoricalLossContextService(
        (_HistoricalLossProvider(),), clock=lambda: NOW
    ).for_event(
        country_code="vnm",
        hazard=Disaster.FLOOD,
        event_occurred_at=NOW,
    )

    assert [record.record_id for record in context.records] == ["desinventar:1999-01"]
    assert context.role == "historical_preparedness_context"
    assert context.current_impact_inference is False
    assert any("not evidence of current impact" in item for item in context.limitations)


@pytest.mark.asyncio
async def test_case_notebook_persists_pins_without_changing_evidence(
    tmp_path: Path,
) -> None:
    path = tmp_path / "operator-workspace.json"
    service = OperatorWorkspaceService(
        JsonOperatorWorkspaceStore(path), clock=lambda: NOW
    )
    notebook = await service.create_notebook(
        title="Mekong flood case review",
        created_by="operator:alice",
        incident_ids=("incident:flood-1",),
    )
    entry = await service.add_notebook_entry(
        notebook_id=notebook.notebook_id,
        kind=NotebookEntryKind.SOURCE_SNAPSHOT,
        title="Initial authority bulletin",
        content="Pinned for later chronology review.",
        reference_id="snapshot:bulletin-1",
        created_by="operator:alice",
    )
    await service.add_notebook_entry(
        notebook_id=notebook.notebook_id,
        kind=NotebookEntryKind.CONCLUSION,
        title="Working conclusion",
        content="The source chronology needs another independent observation.",
        reference_id=None,
        created_by="operator:alice",
    )

    restored = OperatorWorkspaceService(
        JsonOperatorWorkspaceStore(path), clock=lambda: NOW
    )
    notebooks = await restored.notebooks()
    entries = await restored.notebook_entries(notebook.notebook_id)

    assert notebooks == (notebook,)
    assert entries[0] == entry
    assert all(item.evidence is False for item in entries)
    assert all(item.alters_canonical_state is False for item in entries)


def test_source_controlled_terminology_pack_preserves_authority_names() -> None:
    packs_root = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "disaster_monitor"
        / "infrastructure"
        / "localization"
        / "resources"
    )
    resolver = TerminologyResolver(JsonTerminologyPackReader(packs_root))

    assert resolver.term("vi", "hazard.flood") == "Lũ lụt"
    assert resolver.term("vi", "cap.event.tsunami_warning") == "Cảnh báo sóng thần"
    assert resolver.authority_name("vi", "USGS") == "USGS"
    pack = resolver.pack("vi")
    assert pack.human_reviewed is True
    assert pack.version == "1.0.0"


def test_deployment_dependent_p4_capabilities_fail_closed() -> None:
    document = json.loads(
        (REPOSITORY_ROOT / "docs" / "p4-capability-gates.v1.json").read_text(
            encoding="utf-8"
        )
    )
    gates = document["gates"]

    assert document["schema_version"] == "p4-capability-gates.v1"
    assert {item["task"] for item in gates} == {
        111,
        112,
        113,
        114,
        115,
        116,
        117,
        118,
        119,
        127,
        128,
    }
    assert all(item["status"] == "deferred" for item in gates)
    assert all(item["auto_enable"] is False for item in gates)
    assert all(item["required_evidence"] for item in gates)
