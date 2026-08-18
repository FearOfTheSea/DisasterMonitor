import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

from disaster_monitor.application.disaster import DisasterQuery, ProviderBatch
from disaster_monitor.application.services.evidence_reconciliation import (
    EvidenceReconciler,
)
from disaster_monitor.application.services.provider_registry import (
    ProviderCapabilities,
    ProviderRegistration,
    ProviderRegistry,
    ProviderRole,
)
from disaster_monitor.application.services.source_evidence_policy import (
    SourceEvidencePolicyError,
    validate_event_evidence,
    validate_situation_evidence,
)
from disaster_monitor.application.services.source_scouting import SourceScout
from disaster_monitor.application.source_intelligence import (
    CandidateSourceStatus,
    CandidateSourceSubmission,
)
from disaster_monitor.domain.disaster import (
    Country,
    DisasterEvent,
    FactStatus,
    Hazard,
    ReportedFact,
    SituationReport,
    SourceAuthority,
    SourceReference,
)
from disaster_monitor.infrastructure.composition import build_current_disaster_report
from disaster_monitor.infrastructure.configuration import Settings
from disaster_monitor.infrastructure.disaster.composite import (
    CompositeDisasterEventProvider,
)
from disaster_monitor.infrastructure.disaster.errors import (
    DisasterProviderError,
    DisasterProviderResponseError,
    ProviderFailure,
)
from disaster_monitor.infrastructure.disaster.http import validate_network_target
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)
from disaster_monitor.infrastructure.sources.candidate_store import (
    InMemoryCandidateSourceStore,
)
from disaster_monitor.infrastructure.sources.static_source_catalog import (
    StaticSourceCatalog,
)

NOW = datetime(2026, 8, 6, 3, 0, tzinfo=UTC)
FIXTURES = Path(__file__).parent / "fixtures" / "source_intelligence"
COUNTRIES = StaticCountryCatalog()
JAPAN = COUNTRIES.get_by_alpha3("JPN")
VENEZUELA = COUNTRIES.get_by_alpha3("VEN")
assert JAPAN is not None and VENEZUELA is not None


@dataclass(frozen=True, slots=True)
class Metric:
    name: str
    passed: int
    total: int

    @property
    def rate(self) -> float:
        return self.passed / self.total if self.total else 1.0

    def require(self, threshold: float) -> None:
        assert self.rate >= threshold, (
            f"{self.name}: {self.passed}/{self.total} = {self.rate:.4%}, "
            f"required {threshold:.4%}"
        )


def _load(name: str) -> dict[str, object]:
    return cast(
        dict[str, object],
        json.loads((FIXTURES / name).read_text(encoding="utf-8")),
    )


def _query(
    hazard: Hazard = Hazard.EARTHQUAKE, country: Country = JAPAN
) -> DisasterQuery:
    return DisasterQuery(hazard, country, "recent", ("latest developments",))


def _source(
    source_id: str,
    *,
    host: str = "example.test",
    authority: SourceAuthority = SourceAuthority.NATIONAL_AUTHORITY,
    age: timedelta = timedelta(),
) -> SourceReference:
    effective = NOW - age
    return SourceReference(
        source_id,
        source_id,
        f"{source_id} update",
        f"https://{host}/{source_id}",
        effective,
        effective,
        NOW,
        authority,
    )


def _event(
    source_id: str,
    *,
    host: str = "example.test",
    event_id: str = "fixture:event",
    hazard: Hazard = Hazard.EARTHQUAKE,
    country: Country = JAPAN,
    provider_ids: tuple[str, ...] = (),
) -> DisasterEvent:
    return DisasterEvent(
        event_id,
        hazard,
        country.canonical_name,
        country,
        NOW - timedelta(minutes=5),
        _source(source_id, host=host),
        latitude=35.0,
        longitude=135.0,
        magnitude=6.0,
        provider_ids=provider_ids,
    )


@pytest.mark.asyncio
async def test_si_a_release_gate() -> None:
    fixture = _load("coverage_matrix.json")
    countries = cast(list[str], fixture["countries"])
    hazards = cast(list[str], fixture["hazards"])
    roles = cast(list[str], fixture["roles"])
    overrides = {
        (item["country"], item["hazard"], item["role"]): tuple(item["source_ids"])
        for item in cast(list[dict[str, object]], fixture["non_empty"])
    }
    service = build_current_disaster_report(
        Settings(reliefweb_app_name=None), COUNTRIES
    )
    registry = service.provider_registry
    catalog = service.source_catalog
    routing_passed = 0
    routing_total = 0
    for country_code in countries:
        country = COUNTRIES.get_by_alpha3(country_code)
        assert country is not None
        for hazard_name in hazards:
            query = _query(Hazard(hazard_name), country)
            for role_name in roles:
                role = ProviderRole(role_name)
                actual = tuple(
                    item.source_id
                    for item in registry.select(query, role).registrations
                )
                expected = overrides.get((country_code, hazard_name, role_name), ())
                routing_total += 1
                routing_passed += actual == expected
    for item in cast(list[dict[str, object]], fixture["event_conditioned"]):
        country = COUNTRIES.get_by_alpha3(cast(str, item["country"]))
        assert country is not None
        source_id = cast(str, item["event_source_id"])
        descriptor = catalog.get(source_id)
        assert descriptor is not None
        event = _event(
            source_id,
            host=descriptor.allowed_hosts[0],
            event_id=cast(str, item["event_id"]),
            country=country,
            provider_ids=tuple(cast(list[str], item["provider_ids"])),
        )
        actual = tuple(
            registration.source_id
            for registration in registry.select(
                _query(Hazard(cast(str, item["hazard"])), country),
                ProviderRole.SITUATION_EVIDENCE,
                event=event,
            ).registrations
        )
        expected = tuple(cast(list[str], item["source_ids"]))
        routing_total += 1
        routing_passed += actual == expected
    Metric("si_a.routing", routing_passed, routing_total).require(0.99)

    provenance_passed = 0
    for registration in registry.registrations:
        descriptor = catalog.get(registration.source_id or "")
        adapter_source_id = getattr(registration.provider, "source_id", None)
        adapter_hosts = frozenset(
            getattr(registration.provider, "allowed_hosts", frozenset())
        )
        valid = (
            descriptor is not None
            and registration.source_id == adapter_source_id == descriptor.source_id
            and registration.allowed_hosts
            == adapter_hosts
            == frozenset(descriptor.allowed_hosts)
        )
        if valid and descriptor is not None:
            country_code = (
                descriptor.country_codes[0]
                if descriptor.country_codes is not None
                else "JPN"
            )
            country = COUNTRIES.get_by_alpha3(country_code)
            assert country is not None
            query = _query(descriptor.supported_hazards[0], country)
            host = descriptor.allowed_hosts[0]
            try:
                if ProviderRole.EVENT_DISCOVERY in registration.capabilities.roles:
                    validate_event_evidence(
                        _event(
                            descriptor.source_id,
                            host=host,
                            hazard=query.hazard,
                            country=country,
                        ),
                        query,
                        source_id=descriptor.source_id,
                        allowed_hosts=frozenset(descriptor.allowed_hosts),
                    )
                else:
                    validate_situation_evidence(
                        SituationReport(
                            _source(descriptor.source_id, host=host),
                            "Validated provider fixture.",
                            hazard=query.hazard,
                            country_codes=(country.alpha3_code,),
                        ),
                        query,
                        source_id=descriptor.source_id,
                        allowed_hosts=frozenset(descriptor.allowed_hosts),
                    )
            except SourceEvidencePolicyError:
                valid = False
        provenance_passed += bool(valid)
    Metric("si_a.provenance", provenance_passed, len(registry.registrations)).require(
        1.0
    )

    approved_hosts = frozenset({"approved.example"})
    blocked = 0
    adversarial_targets = []
    for index in range(100):
        adversarial_targets.extend(
            (
                f"http://approved.example/{index}",
                f"https://approved.example.evil.test/{index}",
                f"https://user:secret@approved.example/{index}",
                f"https://approved.example:444/{index}",
            )
        )
    for target in adversarial_targets:
        with pytest.raises(DisasterProviderResponseError):
            validate_network_target(target, approved_hosts)
        blocked += 1
    Metric("si_a.network_policy", blocked, len(adversarial_targets)).require(1.0)
    validate_network_target("https://approved.example/feed", approved_hosts)

    malformed_passed, malformed_total = _run_schema_mutations()
    Metric("si_a.malformed_rejection", malformed_passed, malformed_total).require(0.995)
    await service.aclose()


def _run_schema_mutations() -> tuple[int, int]:
    query = _query()
    valid = _event("approved-events")
    wrong_country = replace(valid, country=VENEZUELA)
    naive = replace(valid, event_time=valid.event_time.replace(tzinfo=None))
    string_hazard = replace(valid, hazard=cast(Hazard, "earthquake"))
    string_authority_source = replace(
        _source("approved-events"),
        authority=cast(SourceAuthority, "national_authority"),
    )
    event_mutations: tuple[object, ...] = (
        object(),
        replace(valid, source=_source("wrong-events")),
        replace(valid, source=_source("approved-events", host="evil.test")),
        replace(valid, hazard=Hazard.FLOOD),
        string_hazard,
        wrong_country,
        replace(valid, country=cast(Country, object())),
        naive,
        replace(valid, event_id=""),
        replace(valid, latitude=91.0),
        replace(valid, longitude=181.0),
        replace(valid, magnitude=cast(float, "6.0")),
        replace(valid, source=string_authority_source),
    )
    approved_report_source = _source("approved-reports")
    wrong_report_source = _source("wrong-reports")
    report_mutations: tuple[object, ...] = (
        object(),
        SituationReport(wrong_report_source, "wrong source"),
        SituationReport(
            approved_report_source,
            "wrong hazard",
            hazard=Hazard.FLOOD,
        ),
        SituationReport(
            approved_report_source,
            "wrong country",
            country_codes=("VEN",),
        ),
        SituationReport(
            approved_report_source,
            "wrong fact source",
            facts=(
                ReportedFact(
                    "fatalities",
                    "Fatalities",
                    "3",
                    FactStatus.CONFIRMED,
                    wrong_report_source,
                ),
            ),
        ),
        SituationReport(
            approved_report_source,
            "wrong fact collection",
            facts=cast(tuple[ReportedFact, ...], []),
        ),
        SituationReport(
            approved_report_source,
            "wrong fact value",
            facts=(
                ReportedFact(
                    "fatalities",
                    "Fatalities",
                    cast(str, 3),
                    FactStatus.CONFIRMED,
                    approved_report_source,
                ),
            ),
        ),
    )
    passed = 0
    total = 0
    for _index in range(50):
        for mutation in event_mutations:
            total += 1
            with pytest.raises(SourceEvidencePolicyError):
                validate_event_evidence(
                    mutation,
                    query,
                    source_id="approved-events",
                    allowed_hosts=frozenset({"example.test"}),
                )
            passed += 1
        for mutation in report_mutations:
            total += 1
            with pytest.raises(SourceEvidencePolicyError):
                validate_situation_evidence(
                    mutation,
                    query,
                    source_id="approved-reports",
                    allowed_hosts=frozenset({"example.test"}),
                )
            passed += 1
    return passed, total


class _EpisodeProvider:
    def __init__(self, name: str, source_id: str, outcome: str) -> None:
        self.provider_name = name
        self.source_id = source_id
        self.allowed_hosts = frozenset({"example.test"})
        self._outcome = outcome

    async def find_recent_events(
        self, query: DisasterQuery, *, now: datetime
    ) -> ProviderBatch[DisasterEvent]:
        if self._outcome == "timeout":
            raise DisasterProviderError(
                "timeout", failure=ProviderFailure("timeout", retryable=True)
            )
        if self._outcome == "malformed":
            return cast(ProviderBatch[DisasterEvent], ProviderBatch((object(),)))
        return ProviderBatch(
            (
                _event(
                    self.source_id,
                    event_id=f"{self.source_id}:event",
                    hazard=query.hazard,
                    country=query.country,
                ),
            )
        )


def _episode_registry(primary: str, secondary: str) -> ProviderRegistry:
    providers = (
        _EpisodeProvider("Primary", "primary-events", primary),
        _EpisodeProvider("Secondary", "secondary-events", secondary),
    )
    capabilities = ProviderCapabilities(
        frozenset({ProviderRole.EVENT_DISCOVERY}),
        frozenset({Hazard.EARTHQUAKE}),
        frozenset({"JPN"}),
    )
    return ProviderRegistry(
        tuple(
            ProviderRegistration(
                provider.provider_name,
                provider,
                capabilities,
                source_id=provider.source_id,
                allowed_hosts=provider.allowed_hosts,
                event_provider=provider,
            )
            for provider in providers
        )
    )


@pytest.mark.asyncio
async def test_si_b_release_gate() -> None:
    fixture = _load("acquisition_cases.json")
    truthful = 0
    total = 0
    recovered = 0
    obtainable = 0
    for group in cast(list[dict[str, object]], fixture["cases"]):
        kind = cast(str, group["kind"])
        count = cast(int, group["count"])
        for _index in range(count):
            total += 1
            if kind == "timeout_with_recovery":
                outcome = await _run_acquisition_episode("timeout", "success")
            elif kind == "malformed_with_recovery":
                outcome = await _run_acquisition_episode("malformed", "success")
            elif kind == "partial_source_loss":
                outcome = await _run_acquisition_episode("success", "timeout")
            elif kind == "complete_outage":
                outcome = await _run_acquisition_episode("timeout", "timeout")
            elif kind == "contradictory_revision":
                outcome = _contradictory_revision_is_truthful()
            else:
                outcome = _missing_value_is_truthful()
            truthful += outcome
            if cast(bool, group["obtainable"]):
                obtainable += 1
                recovered += outcome
    Metric("si_b.truthful_outcomes", truthful, total).require(0.995)
    Metric("si_b.recovery", recovered, obtainable).require(0.95)


async def _run_acquisition_episode(primary: str, secondary: str) -> bool:
    result = await CompositeDisasterEventProvider(
        _episode_registry(primary, secondary)
    ).find_recent_events(_query(), now=NOW)
    expected_records = int(primary == "success") + int(secondary == "success")
    expected_issues = int(primary != "success") + int(secondary != "success")
    return (
        len(result.records) == expected_records
        and len(result.issues) == expected_issues
        and all(
            record.source.source_id in {"primary-events", "secondary-events"}
            for record in result.records
        )
        and all(
            issue.reason_code in {"timeout", "source_policy_violation"}
            for issue in result.issues
        )
    )


def _contradictory_revision_is_truthful() -> bool:
    old = _source("official-reports", age=timedelta(hours=2))
    new = _source("official-reports", age=timedelta(minutes=5))
    supplementary = _source(
        "supplementary-reports",
        authority=SourceAuthority.HUMANITARIAN_AGGREGATOR,
        age=timedelta(minutes=2),
    )
    reports = (
        _fatality_report(old, "2"),
        _fatality_report(new, "3"),
        _fatality_report(supplementary, "5", FactStatus.PRELIMINARY),
    )
    packet = EvidenceReconciler().build(
        _query(),
        _event("approved-events"),
        reports,
        warnings=(),
        retrieved_at=NOW,
    )
    return bool(packet.facts and packet.facts[0].value == "3" and packet.conflicts)


def _fatality_report(
    source: SourceReference,
    value: str,
    status: FactStatus = FactStatus.CONFIRMED,
) -> SituationReport:
    return SituationReport(
        source,
        f"Fatalities reported: {value}",
        (
            ReportedFact(
                "fatalities",
                "Fatalities",
                value,
                status,
                source,
                claim_id="fatalities",
            ),
        ),
    )


def _missing_value_is_truthful() -> bool:
    packet = EvidenceReconciler().build(
        _query(),
        _event("approved-events"),
        (),
        warnings=(),
        retrieved_at=NOW,
    )
    return (
        packet.facts == () and packet.partial and "0" not in " ".join(packet.warnings)
    )


def test_si_c_release_gate() -> None:
    fixture = _load("source_scout_cases.json")
    catalog = StaticSourceCatalog()
    before = catalog.sources()
    store = InMemoryCandidateSourceStore()
    scout = SourceScout(catalog, store)
    true_positive = 0
    predicted_positive = 0
    role_matches = 0
    role_total = 0
    separation_passed = 0
    variants = cast(int, fixture["variants_per_case"])
    cases = cast(list[dict[str, object]], fixture["cases"])
    for item in cases:
        for variant in range(variants):
            candidate_id = f"{item['id']}-{variant}"
            record = scout.assess(
                CandidateSourceSubmission(
                    candidate_id,
                    "" if item.get("empty_identity") else candidate_id,
                    f"{item['url']}?variant={variant}",
                    tuple(cast(list[str], item["signals"])),
                    tuple(Hazard(value) for value in cast(list[str], item["hazards"])),
                    (
                        None
                        if item["countries"] is None
                        else tuple(cast(list[str], item["countries"]))
                    ),
                    claimed_organization="Unverified candidate",
                    claimed_domain=cast(str | None, item["claimed_domain"]),
                    claimed_authority=cast(str | None, item.get("claimed_authority")),
                )
            )
            predicted = record.status == CandidateSourceStatus.AWAITING_HUMAN_APPROVAL
            expected = cast(bool, item["expected_relevant"])
            predicted_positive += predicted
            true_positive += predicted and expected
            role_total += 1
            role_matches += tuple(
                role.value for role in record.inferred_roles
            ) == tuple(cast(list[str], item["expected_roles"]))
            separation_passed += (
                catalog.get(candidate_id) is None
                and not hasattr(record, "authority")
                and (
                    not predicted
                    or record.status == CandidateSourceStatus.AWAITING_HUMAN_APPROVAL
                )
            )
    Metric("si_c.precision", true_positive, predicted_positive).require(0.95)
    Metric("si_c.role_classification", role_matches, role_total).require(0.95)
    Metric("si_c.store_separation", separation_passed, role_total).require(1.0)
    assert catalog.sources() == before
    assert len(store.candidates()) == len(cases) * variants
