import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from itertools import islice, permutations
from pathlib import Path
from typing import cast

from evidence_world_state_metrics import (
    EventIdentityMetrics,
    brier_score,
    expected_calibration_error,
    hypothesis_separation_rate,
    merge_counts,
    metric_rate,
    score_labels,
    score_partition,
)

from disaster_monitor.application.disaster import DisasterQuery
from disaster_monitor.application.services.event_resolution import (
    EarthquakeEventPolicy,
    event_observation_key,
)
from disaster_monitor.application.services.evidence_reconciliation import (
    EvidenceReconciler,
)
from disaster_monitor.application.services.hypothesis_reasoning import (
    HypothesisGenerator,
)
from disaster_monitor.domain.disaster import (
    CorrelationStatus,
    DisasterEvent,
    FactStatus,
    Hazard,
    HypothesisArtifact,
    HypothesisTruthStatus,
    ReportedFact,
    SituationReport,
    SourceAuthority,
    SourceReference,
)
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)

NOW = datetime(2026, 8, 6, 3, 0, tzinfo=UTC)
FIXTURES = Path(__file__).parent / "fixtures" / "evidence_world_state"
COUNTRIES = StaticCountryCatalog()


def _load(name: str) -> dict[str, object]:
    return cast(
        dict[str, object],
        json.loads((FIXTURES / name).read_text(encoding="utf-8")),
    )


def _event(item: dict[str, object]) -> DisasterEvent:
    observation_id = cast(str, item["id"])
    country = COUNTRIES.get_by_alpha3(cast(str, item.get("country", "JPN")))
    assert country is not None
    source_id = cast(str, item["source_id"])
    retrieved_at = NOW + timedelta(minutes=cast(int, item.get("retrieved_minutes", 1)))
    source = SourceReference(
        source_id,
        source_id,
        f"Fixture {observation_id}",
        cast(
            str,
            item.get(
                "canonical_url",
                f"https://example.test/{source_id}/{observation_id}",
            ),
        ),
        NOW,
        NOW,
        retrieved_at,
    )
    raw_event_time = item.get("event_time")
    event_time = (
        datetime.fromisoformat(cast(str, raw_event_time).replace("Z", "+00:00"))
        if raw_event_time is not None
        else NOW + timedelta(seconds=cast(int, item["seconds"]))
    )
    return DisasterEvent(
        event_id=cast(str, item["event_id"]),
        hazard=Hazard(cast(str, item.get("hazard", "earthquake"))),
        location=f"Fixture location {observation_id}",
        country=country,
        event_time=event_time,
        source=source,
        latitude=cast(float | None, item["lat"]),
        longitude=cast(float | None, item["lon"]),
        magnitude=cast(float | None, item["magnitude"]),
        is_aftershock=cast(bool, item.get("is_aftershock", False)),
        parent_event_id=cast(str | None, item.get("parent_event_id")),
        provider_ids=tuple(cast(list[str], item.get("provider_ids", []))),
    )


def _fixture_key_map(
    items: list[dict[str, object]], events: tuple[DisasterEvent, ...]
) -> dict[str, str]:
    return {
        cast(str, item["id"]): event_observation_key(event)
        for item, event in zip(items, events, strict=True)
    }


def test_ew_a_release_gate() -> None:
    fixture = _load("physical_event_identity.json")
    permutation_count = cast(int, fixture["permutations_per_episode"])
    policy = EarthquakeEventPolicy()
    metrics = EventIdentityMetrics()
    for episode in cast(list[dict[str, object]], fixture["episodes"]):
        items = cast(list[dict[str, object]], episode["observations"])
        events = tuple(_event(item) for item in items)
        keys = _fixture_key_map(items, events)
        expected_groups = tuple(
            frozenset(keys[item] for item in cast(list[str], group))
            for group in cast(list[list[str]], episode["groups"])
        )
        expected_ambiguous = frozenset(
            keys[item] for item in cast(list[str], episode["ambiguous_assignments"])
        )
        expected_snapshot: tuple[tuple[str, str, tuple[str, ...]], ...] | None = None
        for ordered in islice(permutations(events), permutation_count):
            identity = policy.identify(tuple(ordered))
            predicted_groups = tuple(
                frozenset(event_observation_key(item) for item in physical.observations)
                for physical in identity.physical_events
            )
            correct, total, conflations = score_partition(
                expected_groups, predicted_groups
            )
            query_country = events[0].country
            query_hazard = events[0].hazard
            resolution = policy.resolve(
                tuple(ordered),
                DisasterQuery(
                    query_hazard,
                    query_country,
                    "recent",
                    ("latest",),
                    time_window_days=2_000,
                ),
                now=NOW + timedelta(days=1),
            )
            predicted_ambiguous = frozenset(
                item.observation_key for item in identity.ambiguous_assignments
            )
            snapshot = tuple(
                (
                    physical.physical_event_id,
                    physical.event.event_id,
                    tuple(
                        event_observation_key(item) for item in physical.observations
                    ),
                )
                for physical in identity.physical_events
            )
            if expected_snapshot is None:
                expected_snapshot = snapshot
            assert snapshot == expected_snapshot, episode["id"]
            cross_scope_merges = sum(
                len({item.hazard for item in physical.observations}) > 1
                or len({item.country.alpha3_code for item in physical.observations}) > 1
                for physical in identity.physical_events
            )
            ambiguity_exact = (
                predicted_ambiguous == expected_ambiguous
                and resolution.ambiguous == cast(bool, episode["resolution_ambiguous"])
            )
            intentionally_confusable = bool(expected_ambiguous) or cast(
                bool, episode["resolution_ambiguous"]
            )
            if not intentionally_confusable:
                assert ambiguity_exact, episode["id"]
            metrics = replace(
                metrics,
                assignment_correct=metrics.assignment_correct + correct,
                assignment_total=metrics.assignment_total + total,
                ambiguity_correct=metrics.ambiguity_correct
                + (ambiguity_exact if intentionally_confusable else 0),
                ambiguity_total=metrics.ambiguity_total + int(intentionally_confusable),
                prohibited_conflations=metrics.prohibited_conflations + conflations,
                cross_scope_merges=metrics.cross_scope_merges + cross_scope_merges,
            )

    assert metrics.assignment_rate >= 0.995, metrics
    assert metrics.ambiguity_rate >= 0.99, metrics
    assert metrics.prohibited_conflations == 0, metrics
    assert metrics.cross_scope_merges == 0, metrics


def test_ew_a_evaluator_rejects_forced_cross_event_merge() -> None:
    expected = (frozenset({"a"}), frozenset({"b"}))
    predicted = (frozenset({"a", "b"}),)

    correct, total, prohibited = score_partition(expected, predicted)

    assert correct / total < 0.995
    assert prohibited == 1


def _fixture_time(item: dict[str, object], name: str) -> datetime | None:
    value = item.get(name)
    if value is None:
        return None
    return NOW - timedelta(hours=float(cast(int | float, value)))


def _temporal_report(item: dict[str, object]) -> SituationReport:
    report_id = cast(str, item["id"])
    source_id = cast(str, item["source_id"])
    source = SourceReference(
        source_id=source_id,
        publisher=source_id,
        title=report_id,
        canonical_url=f"https://example.test/{source_id}/{report_id}",
        published_at=_fixture_time(item, "published_hours_ago"),
        updated_at=_fixture_time(item, "updated_hours_ago"),
        retrieved_at=NOW
        - timedelta(hours=float(cast(int | float, item.get("retrieved_hours_ago", 0)))),
        authority=SourceAuthority(cast(str, item["authority"])),
    )
    facts = tuple(
        ReportedFact(
            category=cast(str, fact["claim"]),
            label=cast(str, fact["claim"]).replace("_", " ").title(),
            value=cast(str, fact["value"]),
            status=FactStatus(cast(str, fact["status"])),
            source=source,
            observed_at=_fixture_time(item, "observed_hours_ago"),
            claim_id=cast(str, fact["claim"]),
        )
        for fact in cast(list[dict[str, object]], item["facts"])
    )
    correlation = item.get("correlation")
    hazard = item.get("hazard")
    return SituationReport(
        source=source,
        narrative=cast(str, item.get("narrative", f"Fixture report {report_id}.")),
        facts=facts,
        event_id=cast(str | None, item.get("event_id")),
        correlation=(
            CorrelationStatus(cast(str, correlation))
            if correlation is not None
            else None
        ),
        hazard=Hazard(cast(str, hazard)) if hazard is not None else None,
    )


def _temporal_event() -> DisasterEvent:
    japan = COUNTRIES.get_by_alpha3("JPN")
    assert japan is not None
    source = SourceReference(
        "fixture-events",
        "Fixture event authority",
        "Selected event",
        "https://example.test/events/fixture",
        NOW - timedelta(hours=2),
        NOW - timedelta(hours=2),
        NOW,
        SourceAuthority.SCIENTIFIC_AUTHORITY,
    )
    return DisasterEvent(
        "fixture:event",
        Hazard.EARTHQUAKE,
        "Fixture location, Japan",
        japan,
        NOW - timedelta(hours=3),
        source,
        latitude=35.0,
        longitude=135.0,
        magnitude=6.0,
    )


def test_ew_b_release_gate() -> None:
    fixture = _load("temporal_evidence.json")
    permutation_count = cast(int, fixture["permutations_per_episode"])
    event = _temporal_event()
    query = DisasterQuery(event.hazard, event.country, "recent", ("latest",))
    disposition_counts: dict[str, tuple[int, int]] = {}
    freshness_counts: dict[str, tuple[int, int]] = {}
    missingness_counts: dict[str, tuple[int, int]] = {}
    lineage_passed = 0
    lineage_total = 0
    history_passed = 0
    history_total = 0

    for episode in cast(list[dict[str, object]], fixture["episodes"]):
        reports = tuple(
            _temporal_report(item)
            for item in cast(list[dict[str, object]], episode["reports"])
        )
        expected_claims = cast(dict[str, dict[str, object]], episode["claims"])
        expected_snapshot: tuple[object, ...] | None = None
        for replay_index, ordered in enumerate(
            islice(permutations(reports), permutation_count)
        ):
            packet = EvidenceReconciler().build(
                query,
                event,
                tuple(ordered),
                warnings=(),
                retrieved_at=NOW,
            )
            state = packet.world_state
            assert state is not None
            snapshot = (
                state.state_version,
                tuple(
                    (
                        claim.claim_key,
                        claim.availability.value,
                        claim.current.fact.value if claim.current else None,
                        tuple(
                            (
                                item.observation.observation_id,
                                item.disposition.value,
                                item.freshness.value,
                            )
                            for item in claim.history
                        ),
                        tuple(
                            source.canonical_url for source in claim.omission_reports
                        ),
                    )
                    for claim in state.claims
                ),
            )
            if expected_snapshot is None:
                expected_snapshot = snapshot
            assert snapshot == expected_snapshot, episode["id"]

            for claim_key, expected in expected_claims.items():
                claim = state.claim(claim_key)
                current_value = claim.current.fact.value if claim.current else None
                assert current_value == cast(str | None, expected["current"]), (
                    episode["id"],
                    claim_key,
                )
                expected_dispositions = cast(dict[str, str], expected["dispositions"])
                predicted_dispositions = {
                    item.observation.report.source.title: item.disposition.value
                    for item in claim.history
                }
                expected_freshness = cast(dict[str, str], expected["freshness"])
                predicted_freshness = {
                    item.observation.report.source.title: item.freshness.value
                    for item in claim.history
                }
                assert tuple(
                    source.title for source in claim.omission_reports
                ) == tuple(cast(list[str], expected.get("omissions", [])))
                suffix = f"{episode['id']}:{claim_key}:{replay_index}"
                merge_counts(
                    disposition_counts,
                    score_labels(expected_dispositions, predicted_dispositions),
                )
                merge_counts(
                    freshness_counts,
                    score_labels(expected_freshness, predicted_freshness),
                )
                merge_counts(
                    missingness_counts,
                    score_labels(
                        {suffix: cast(str, expected["availability"])},
                        {suffix: claim.availability.value},
                    ),
                )
                history_total += 1
                history_passed += set(predicted_dispositions) == set(
                    expected_dispositions
                )
                if claim.current is not None:
                    lineage_total += 1
                    current = claim.current
                    lineage_passed += (
                        current.fact in current.report.facts
                        and current.fact.source == current.report.source
                        and current.chronology.retrieved_at
                        == current.fact.source.retrieved_at
                        and current.chronology.effective_at
                        in {
                            current.chronology.updated_at,
                            current.chronology.published_at,
                            current.chronology.observed_at,
                            current.chronology.retrieved_at,
                        }
                    )
            assert {fact.claim_id: fact.value for fact in packet.facts} == {
                claim_key: cast(str, expected["current"])
                for claim_key, expected in expected_claims.items()
                if expected["current"] is not None
            }

    assert lineage_passed / lineage_total == 1.0, (
        "ew_b.lineage",
        lineage_passed,
        lineage_total,
    )
    assert history_passed / history_total == 1.0, (
        "ew_b.history_preservation",
        history_passed,
        history_total,
    )
    for label, counts in disposition_counts.items():
        assert metric_rate(counts) >= 0.995, (f"ew_b.disposition.{label}", counts)
    aggregate_disposition = (
        sum(passed for passed, _total in disposition_counts.values()),
        sum(total for _passed, total in disposition_counts.values()),
    )
    assert metric_rate(aggregate_disposition) >= 0.995, (
        "ew_b.disposition.aggregate",
        aggregate_disposition,
    )
    for label, counts in missingness_counts.items():
        assert metric_rate(counts) >= 0.995, (f"ew_b.missingness.{label}", counts)
    for label, counts in freshness_counts.items():
        assert metric_rate(counts) >= 0.99, (f"ew_b.freshness.{label}", counts)


def test_ew_b_evaluator_rejects_destructive_history_and_missing_as_zero() -> None:
    history_fault = score_labels(
        {"old": "superseded", "new": "current"},
        {"new": "current"},
    )
    missing_fault = score_labels({"fatalities": "absent"}, {"fatalities": "present"})

    assert metric_rate(history_fault["superseded"]) < 0.995
    assert metric_rate(missing_fault["absent"]) < 0.995


def _hypothesis_report(item: dict[str, object], *, variant: int) -> SituationReport:
    report_id = cast(str, item["id"])
    source_id = cast(str, item["source_id"])
    effective_at = NOW - timedelta(hours=float(cast(int | float, item["hours_ago"])))
    source = SourceReference(
        source_id,
        source_id,
        f"{report_id}-variant-{variant}",
        f"https://example.test/{source_id}/{report_id}/{variant}",
        effective_at,
        effective_at,
        NOW,
        SourceAuthority(cast(str, item["authority"])),
    )
    return SituationReport(
        source,
        f"Frozen hypothesis episode {report_id} variant {variant}.",
        tuple(
            ReportedFact(
                category=cast(str, fact["claim"]),
                label=cast(str, fact["claim"]).title(),
                value=cast(str, fact["value"]),
                status=FactStatus(cast(str, fact["status"])),
                source=source,
                claim_id=cast(str, fact["claim"]),
            )
            for fact in cast(list[dict[str, object]], item["facts"])
        ),
    )


def test_ew_c_release_gate() -> None:
    fixture = _load("hypothesis_outcomes.json")
    event = _temporal_event()
    query = DisasterQuery(event.hazard, event.country, "recent", ("latest",))
    generator = HypothesisGenerator()
    predictions: list[float] = []
    outcomes: list[int] = []
    hypotheses: list[HypothesisArtifact] = []
    observed_products: list[object] = []

    for case in cast(list[dict[str, object]], fixture["cases"]):
        variants = cast(int, case["variants"])
        outcome_cycle = cast(list[int] | None, case.get("outcomes"))
        for variant in range(variants):
            reports = tuple(
                _hypothesis_report(item, variant=variant)
                for item in cast(list[dict[str, object]], case["reports"])
            )
            ordered = reports if variant % 2 == 0 else tuple(reversed(reports))
            packet = EvidenceReconciler().build(
                query,
                event,
                ordered,
                warnings=(),
                retrieved_at=NOW,
            )
            state = packet.world_state
            assert state is not None
            generated = generator.generate(state)
            replay = (
                EvidenceReconciler()
                .build(
                    query,
                    event,
                    tuple(reversed(ordered)),
                    warnings=(),
                    retrieved_at=NOW,
                )
                .world_state
            )
            assert replay is not None
            assert generator.generate(replay) == generated
            assert len(generated) == 1
            hypothesis = generated[0]
            evidence_ids = {
                item.observation.observation_id
                for claim in state.claims
                for item in claim.history
            }
            assert set(hypothesis.supporting_evidence_ids) <= evidence_ids
            assert set(hypothesis.contradicting_evidence_ids) <= evidence_ids
            assert set(hypothesis.uncertain_evidence_ids) <= evidence_ids
            assert hypothesis.state_version == state.state_version
            assert hypothesis.evaluated_at == state.evaluated_at
            assert hypothesis.rationale_features
            assert hypothesis.truth_status == HypothesisTruthStatus.INFERRED
            assert not isinstance(hypothesis, ReportedFact)
            predictions.append(hypothesis.probability)
            if outcome_cycle is not None:
                outcomes.append(outcome_cycle[variant % len(outcome_cycle)])
            else:
                outcomes.append(cast(int, case["outcome"]))
            hypotheses.append(hypothesis)
            observed_products.extend(packet.facts)

    bins = cast(int, fixture["calibration_bins"])
    baseline_probability = cast(float, fixture["naive_baseline_probability"])
    ece = expected_calibration_error(predictions, outcomes, bins=bins)
    actual_brier = brier_score(predictions, outcomes)
    baseline_brier = brier_score([baseline_probability] * len(outcomes), outcomes)
    typing_rate = hypothesis_separation_rate(hypotheses, observed_products)

    assert ece <= 0.05, ("ew_c.ece", ece)
    assert actual_brier < baseline_brier, (
        "ew_c.brier",
        actual_brier,
        baseline_brier,
    )
    assert typing_rate == 1.0, ("ew_c.inference_typing", typing_rate)


def test_ew_c_evaluator_rejects_miscalibration_and_observation_promotion() -> None:
    predictions = [0.99] * 100
    outcomes = [0] * 100
    event = _temporal_event()
    state = (
        EvidenceReconciler()
        .build(
            DisasterQuery(event.hazard, event.country, "recent", ("latest",)),
            event,
            (),
            warnings=(),
            retrieved_at=NOW,
        )
        .world_state
    )
    assert state is not None
    hypothesis = HypothesisGenerator().generate(state)[0]

    assert expected_calibration_error(predictions, outcomes, bins=10) > 0.05
    assert brier_score(predictions, outcomes) > brier_score([0.5] * 100, outcomes)
    assert hypothesis_separation_rate([hypothesis], [hypothesis]) < 1.0
