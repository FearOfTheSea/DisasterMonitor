from dataclasses import replace
from datetime import UTC, datetime, timedelta

from disaster_monitor.application.services.memory_policy import (
    MemoryPolicy,
    MemoryPolicyAction,
)
from disaster_monitor.domain.memory import (
    MemoryAuthority,
    MemoryCandidate,
    MemoryLifecycleStatus,
    MemoryType,
)

NOW = datetime(2026, 8, 24, 12, tzinfo=UTC)


def candidate(**changes) -> MemoryCandidate:
    value = MemoryCandidate(
        candidate_id="candidate:one",
        schema_version="agent-memory.v1",
        memory_type=MemoryType.PHYSICAL_EVENT_REFERENCE,
        summary=(
            "Historical investigation reference for a flood in Testland; current "
            "conditions require newly admitted evidence."
        ),
        conversation_id="conversation-a",
        physical_event_id="physical-event:one",
        disaster_identifier="flood",
        country_code="TST",
        source_message_ids=("message-user", "message-assistant"),
        evidence_ids=("physical-event:one",),
        world_state_version="state:one",
        created_at=NOW,
        confirmed_at=NOW,
        expires_at=NOW + timedelta(days=30),
        confidence=1.0,
    )
    return replace(value, **changes)


def test_policy_accepts_only_non_authoritative_high_confidence_reference() -> None:
    decision = MemoryPolicy().evaluate(candidate(), (), now=NOW)

    assert decision.action is MemoryPolicyAction.ACCEPTED
    assert decision.record is not None
    assert decision.record.status is MemoryLifecycleStatus.ACTIVE
    assert decision.record.authority is MemoryAuthority.HISTORICAL_CONTEXT
    assert decision.record.may_satisfy_current_evidence is False
    assert decision.record.memory_id.startswith("memory:")


def test_policy_rejects_low_confidence_or_volatile_current_claims() -> None:
    policy = MemoryPolicy()

    low_confidence = policy.evaluate(candidate(confidence=0.89), (), now=NOW)
    volatile_claim = policy.evaluate(
        candidate(summary="Currently 12 people are confirmed dead."), (), now=NOW
    )

    assert low_confidence.action is MemoryPolicyAction.REJECTED
    assert low_confidence.reason == "candidate_confidence_below_policy"
    assert volatile_claim.action is MemoryPolicyAction.REJECTED
    assert volatile_claim.reason == "volatile_or_authoritative_summary"


def test_policy_merges_same_state_and_supersedes_changed_state() -> None:
    policy = MemoryPolicy()
    first = policy.evaluate(candidate(), (), now=NOW).record
    assert first is not None

    merged = policy.evaluate(
        candidate(
            candidate_id="candidate:merge",
            source_message_ids=("message-user-2", "message-assistant-2"),
            evidence_ids=("physical-event:one", "observation:one"),
            confirmed_at=NOW + timedelta(hours=1),
        ),
        (first,),
        now=NOW + timedelta(hours=1),
    )
    changed = policy.evaluate(
        candidate(
            candidate_id="candidate:changed",
            world_state_version="state:two",
            evidence_ids=("physical-event:one", "observation:two"),
            confirmed_at=NOW + timedelta(hours=2),
        ),
        (merged.record,),
        now=NOW + timedelta(hours=2),
    )

    assert merged.action is MemoryPolicyAction.MERGED
    assert merged.record is not None
    assert merged.record.memory_id == first.memory_id
    assert merged.record.source_message_ids == (
        "message-user",
        "message-assistant",
        "message-user-2",
        "message-assistant-2",
    )
    assert changed.action is MemoryPolicyAction.SUPERSEDED
    assert changed.record is not None
    assert changed.record.world_state_version == "state:two"
    assert changed.superseded_memory_ids == (first.memory_id,)


def test_policy_expires_stale_candidates_without_persisting_them_as_active() -> None:
    decision = MemoryPolicy().evaluate(
        candidate(expires_at=NOW - timedelta(seconds=1)), (), now=NOW
    )

    assert decision.action is MemoryPolicyAction.EXPIRED
    assert decision.record is None
    assert decision.reason == "candidate_expired"
