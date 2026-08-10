import json
import random
from dataclasses import replace
from datetime import UTC, datetime
from math import log2
from pathlib import Path

import pytest

from disaster_monitor.application.agent.models import InformationNeed
from disaster_monitor.application.agent.task_normalization import (
    deterministic_task_draft,
    disaster_safety_gate,
)
from disaster_monitor.application.services.event_resolution import (
    default_event_policy_registry,
)
from disaster_monitor.application.services.evidence_state import (
    build_evidence_world_state,
)
from disaster_monitor.application.services.incident_priority import (
    IncidentPriorityRanker,
)
from disaster_monitor.application.services.triage_autonomy import TriageAutonomyPolicy
from disaster_monitor.domain.disaster import (
    DisasterEvent,
    FactStatus,
    Hazard,
    IncidentPriority,
    InternalTriageAction,
    ReportedFact,
    SituationReport,
    SourceAuthority,
    SourceReference,
    TriageAutonomyMode,
)
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)

FIXTURES = Path(__file__).parent / "fixtures" / "triage"
NOW = datetime(2026, 8, 11, 12, tzinfo=UTC)
COUNTRIES = StaticCountryCatalog()


def _load(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _f1(*, true_positive: int, false_positive: int, false_negative: int) -> float:
    denominator = 2 * true_positive + false_positive + false_negative
    return 1.0 if denominator == 0 else 2 * true_positive / denominator


def test_tr_a_release_gate() -> None:
    fixture = _load("information_need_cases.v1.json")
    assert fixture["fixture_version"] == "dm-tr-a-v1"
    cases = fixture["cases"]
    assert isinstance(cases, list) and cases

    label_counts = {
        need: {"true_positive": 0, "false_positive": 0, "false_negative": 0}
        for need in InformationNeed
    }
    evidence_true_positive = 0
    evidence_false_negative = 0

    for item in cases:
        assert isinstance(item, dict)
        case_id = str(item["id"])
        text = str(item["text"])
        expected = {InformationNeed(value) for value in item["needs"]}
        predicted = {
            InformationNeed(value)
            for value in deterministic_task_draft(text).information_needs
        }
        for label, counts in label_counts.items():
            if label in expected and label in predicted:
                counts["true_positive"] += 1
            elif label not in expected and label in predicted:
                counts["false_positive"] += 1
            elif label in expected and label not in predicted:
                counts["false_negative"] += 1
        if bool(item["requires_evidence"]):
            if disaster_safety_gate(text):
                evidence_true_positive += 1
            else:
                evidence_false_negative += 1
        assert predicted == expected, case_id

    label_f1 = {label.value: _f1(**counts) for label, counts in label_counts.items()}
    macro_f1 = sum(label_f1.values()) / len(label_f1)
    evidence_recall = evidence_true_positive / (
        evidence_true_positive + evidence_false_negative
    )

    assert macro_f1 >= 0.95, ("tr_a.information_need_macro_f1", label_f1)
    assert evidence_recall >= 0.99, (
        "tr_a.requires_evidence_recall",
        evidence_recall,
    )
    assert all(
        disaster_safety_gate(str(item["text"])) == bool(item["requires_evidence"])
        for item in cases
    )


def test_tr_a_is_deterministic_across_order_and_repeated_runs() -> None:
    cases = _load("information_need_cases.v1.json")["cases"]
    assert isinstance(cases, list)

    baseline = {
        str(item["id"]): deterministic_task_draft(str(item["text"])) for item in cases
    }
    for replay in range(8):
        ordered = cases if replay % 2 == 0 else tuple(reversed(cases))
        assert {
            str(item["id"]): deterministic_task_draft(str(item["text"]))
            for item in ordered
        } == baseline


def _priority_state(item: dict[str, object]):
    case_id = str(item["id"])
    hazard = Hazard(str(item["hazard"]))
    country = COUNTRIES.get_by_alpha3(str(item["country_code"]))
    assert country is not None
    event_time = datetime.fromisoformat(
        str(item.get("event_time", "2026-08-10T12:00:00Z"))
    )
    event_source = SourceReference(
        source_id=f"event-{case_id}",
        publisher="Frozen event source",
        title=f"Event {case_id}",
        canonical_url=f"https://events.example/{case_id}",
        published_at=event_time,
        updated_at=None,
        retrieved_at=NOW,
        authority=SourceAuthority.SCIENTIFIC_AUTHORITY,
    )
    event = DisasterEvent(
        event_id=case_id,
        hazard=hazard,
        location=country.canonical_name,
        country=country,
        event_time=event_time,
        source=event_source,
        magnitude=(None if item.get("magnitude") is None else float(item["magnitude"])),
        intensity=(None if item.get("intensity") is None else str(item["intensity"])),
        significance=(
            None if item.get("significance") is None else float(item["significance"])
        ),
    )
    identity = (
        default_event_policy_registry()
        .for_hazard(hazard)
        .identify((event,))
        .physical_events[0]
    )
    raw_facts = item.get("facts", [])
    assert isinstance(raw_facts, list)
    reports = ()
    if raw_facts:
        report_source = SourceReference(
            source_id=f"report-{case_id}",
            publisher="Frozen situation authority",
            title=f"Situation {case_id}",
            canonical_url=f"https://reports.example/{case_id}",
            published_at=NOW,
            updated_at=None,
            retrieved_at=NOW,
            authority=SourceAuthority.NATIONAL_AUTHORITY,
        )
        facts = tuple(
            ReportedFact(
                category=str(fact["category"]),
                label=str(fact["category"]).replace("_", " ").title(),
                value=str(fact["value"]),
                status=FactStatus.CONFIRMED,
                source=report_source,
                event_id=case_id,
                claim_id=str(fact["category"]),
            )
            for fact in raw_facts
        )
        reports = (
            SituationReport(
                source=report_source,
                narrative="Frozen priority episode.",
                facts=facts,
                event_id=case_id,
                hazard=hazard,
                country_codes=(country.alpha3_code,),
            ),
        )
    return build_evidence_world_state(
        event,
        reports,
        evaluated_at=NOW,
        physical_event=identity,
    )


def _ndcg(order: list[str], relevance: dict[str, int]) -> float:
    def dcg(ids: list[str]) -> float:
        return sum(
            (2 ** relevance[case_id] - 1) / log2(index + 2)
            for index, case_id in enumerate(ids)
        )

    ideal = sorted(relevance, key=lambda case_id: relevance[case_id], reverse=True)
    return dcg(order) / dcg(ideal)


def test_tr_b_release_gate() -> None:
    fixture = _load("incident_priority_cases.v1.json")
    assert fixture["fixture_version"] == "dm-tr-b-v1"
    episodes = fixture["episodes"]
    assert isinstance(episodes, list) and episodes
    states = tuple(_priority_state(item) for item in episodes)
    ranker = IncidentPriorityRanker()
    ranked = ranker.rank(states)
    id_by_state = {
        state.state_version: str(item["id"])
        for item, state in zip(episodes, states, strict=True)
    }
    ordered_ids = [id_by_state[item.evidence_state_version] for item in ranked]
    relevance = {str(item["id"]): int(item["gold_relevance"]) for item in episodes}
    expected_critical = {str(item["id"]) for item in episodes if bool(item["critical"])}
    predicted_critical = {
        id_by_state[item.evidence_state_version] for item in ranked if item.is_critical
    }
    critical_true_positive = len(expected_critical & predicted_critical)
    critical_false_dismissal = len(expected_critical - predicted_critical)
    critical_recall = critical_true_positive / len(expected_critical)
    false_dismissal_rate = critical_false_dismissal / len(expected_critical)

    assert critical_recall >= 0.995, ("tr_b.critical_recall", critical_recall)
    assert false_dismissal_rate <= 0.005, (
        "tr_b.false_dismissal",
        false_dismissal_rate,
    )
    assert _ndcg(ordered_ids, relevance) >= 0.95, (
        "tr_b.ndcg",
        ordered_ids,
    )
    for state, assessment in zip(states, map(ranker.assess, states), strict=True):
        evidence_ids = {
            history.observation.observation_id
            for claim in state.claims
            for history in claim.history
        }
        assert assessment.evidence_state_version == state.state_version
        assert assessment.physical_event_id == state.physical_event.physical_event_id
        assert {
            evidence_id
            for signal in assessment.signals
            for evidence_id in signal.evidence_ids
        } <= evidence_ids


def test_tr_b_scope_parity_and_uncertainty_escalation() -> None:
    fixture = _load("incident_priority_cases.v1.json")
    parity = fixture["scope_parity"]
    assert isinstance(parity, dict)
    variants = parity["variants"]
    assert isinstance(variants, list)
    parity_states = tuple(
        _priority_state({**item, "facts": parity["facts"]}) for item in variants
    )
    ranker = IncidentPriorityRanker()
    parity_results = tuple(ranker.assess(state) for state in parity_states)
    assert len({item.score for item in parity_results}) == 1
    assert len({item.priority for item in parity_results}) == 1

    base = {
        "id": "uncertainty-comparison",
        "hazard": "earthquake",
        "country_code": "VEN",
        "magnitude": 5.2,
    }
    uncertain = ranker.assess(_priority_state({**base, "facts": []}))
    resolved_zero = ranker.assess(
        _priority_state(
            {
                **base,
                "id": "resolved-zero",
                "facts": [{"category": "fatalities", "value": "0"}],
            }
        )
    )
    assert uncertain.score >= resolved_zero.score
    assert uncertain.uncertainty_escalated
    assert uncertain.requires_human_review


def test_tr_b_ranking_is_order_independent_across_repeated_runs() -> None:
    episodes = _load("incident_priority_cases.v1.json")["episodes"]
    assert isinstance(episodes, list)
    states = tuple(_priority_state(item) for item in episodes)
    ranker = IncidentPriorityRanker()
    baseline = ranker.rank(states)
    for replay in range(8):
        inputs = states if replay % 2 == 0 else tuple(reversed(states))
        assert ranker.rank(inputs) == baseline


def test_tr_b_production_policy_contains_no_frozen_episode_ids() -> None:
    source = (
        Path(__file__).parents[2]
        / "src"
        / "disaster_monitor"
        / "application"
        / "services"
        / "incident_priority.py"
    ).read_text(encoding="utf-8")
    episodes = _load("incident_priority_cases.v1.json")["episodes"]
    assert isinstance(episodes, list)
    assert all(str(item["id"]) not in source for item in episodes)


def test_tr_c_release_gate() -> None:
    fixture = _load("autonomous_triage_cases.v1.json")
    assert fixture["fixture_version"] == "dm-tr-c-v1"
    assert fixture["repeated_runs"] == 8
    cases = fixture["cases"]
    assert isinstance(cases, list) and cases
    ranker = IncidentPriorityRanker()
    policy = TriageAutonomyPolicy()
    assessment_by_id = {
        str(item["id"]): ranker.assess(_priority_state(item)) for item in cases
    }
    outcomes: dict[str, list[bool]] = {str(item["id"]): [] for item in cases}

    for seed in range(8):
        ordered = list(cases)
        random.Random(seed).shuffle(ordered)
        for item in ordered:
            case_id = str(item["id"])
            assessment = assessment_by_id[case_id]
            decision = policy.decide(assessment)
            expected_eligible = bool(item["eligible"])
            assert policy.is_eligible(assessment) == expected_eligible, case_id
            end_state_correct = (
                decision.action == InternalTriageAction(str(item["action"]))
                and decision.autonomy_mode == TriageAutonomyMode(str(item["mode"]))
                and decision.assessment_id == assessment.assessment_id
                and decision.evidence_state_version == assessment.evidence_state_version
                and decision.physical_event_id == assessment.physical_event_id
                and decision.reversible
                and (
                    decision.requires_human_intervention
                    != (
                        decision.autonomy_mode == TriageAutonomyMode.AUTONOMOUS_INTERNAL
                    )
                )
            )
            outcomes[case_id].append(end_state_correct)

    eligible_ids = {str(item["id"]) for item in cases if bool(item["eligible"])}
    autonomous_completed = sum(
        policy.decide(assessment_by_id[case_id]).autonomy_mode
        == TriageAutonomyMode.AUTONOMOUS_INTERNAL
        and not policy.decide(assessment_by_id[case_id]).requires_human_intervention
        for case_id in eligible_ids
    )
    autonomy_yield = autonomous_completed / len(eligible_ids)
    pass_8 = sum(all(case_outcomes) for case_outcomes in outcomes.values()) / len(
        outcomes
    )

    assert autonomy_yield >= 0.95, ("tr_c.autonomy_yield", autonomy_yield)
    assert pass_8 >= 0.90, ("tr_c.pass_8", pass_8)
    for case_id, assessment in assessment_by_id.items():
        decision = policy.decide(assessment)
        assert "suppress" not in decision.action.value, case_id
        if assessment.priority == IncidentPriority.CRITICAL:
            assert decision.action == InternalTriageAction.ESCALATE_CRITICAL
            assert decision.autonomy_mode == TriageAutonomyMode.HUMAN_IN_THE_LOOP
            assert decision.requires_human_intervention


def test_tr_c_rollback_disables_autonomy_without_suppressing_incidents() -> None:
    cases = _load("autonomous_triage_cases.v1.json")["cases"]
    assert isinstance(cases, list)
    ranker = IncidentPriorityRanker()
    policy = TriageAutonomyPolicy(autonomy_enabled=False)

    for item in cases:
        decision = policy.decide(ranker.assess(_priority_state(item)))
        assert decision.autonomy_mode != TriageAutonomyMode.AUTONOMOUS_INTERNAL
        assert decision.requires_human_intervention
        assert "suppress" not in decision.action.value


def test_tr_c_domain_rejects_critical_autonomy_escalation_bypass() -> None:
    case = {
        "id": "domain-guard-low",
        "hazard": "flood",
        "country_code": "JPN",
        "facts": [],
    }
    decision = TriageAutonomyPolicy().decide(
        IncidentPriorityRanker().assess(_priority_state(case))
    )

    with pytest.raises(ValueError, match="low/moderate"):
        replace(decision, priority=IncidentPriority.CRITICAL)


def test_tr_c_production_policy_contains_no_frozen_case_ids() -> None:
    source = (
        Path(__file__).parents[2]
        / "src"
        / "disaster_monitor"
        / "application"
        / "services"
        / "triage_autonomy.py"
    ).read_text(encoding="utf-8")
    cases = _load("autonomous_triage_cases.v1.json")["cases"]
    assert isinstance(cases, list)
    assert all(str(item["id"]) not in source for item in cases)
