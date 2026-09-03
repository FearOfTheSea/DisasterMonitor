import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from disaster_monitor.application.services.decision_support import (
    DecisionOptionGenerator,
)
from disaster_monitor.application.services.event_resolution import (
    default_event_policy_registry,
)
from disaster_monitor.application.services.evidence_state import (
    build_evidence_world_state,
)
from disaster_monitor.application.services.hypothesis_reasoning import (
    HypothesisGenerator,
)
from disaster_monitor.application.services.incident_priority import (
    IncidentPriorityRanker,
)
from disaster_monitor.application.services.triage_autonomy import TriageAutonomyPolicy
from disaster_monitor.domain.decision import DecisionSupportArtifact
from disaster_monitor.domain.disaster import (
    Disaster,
    DisasterEvent,
    EventMeasurement,
    EvidenceWorldState,
    FactStatus,
    HypothesisArtifact,
    IncidentPriorityAssessment,
    InternalTriageDecision,
    MeasurementKind,
    ReportedFact,
    SituationReport,
    SourceAuthority,
    SourceReference,
)
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)

DECISION_SUPPORT_FIXTURES = Path(__file__).parent / "fixtures" / "decision_support"
DECISION_SUPPORT_NOW = datetime(2026, 8, 11, 12, tzinfo=UTC)
COUNTRIES = StaticCountryCatalog()


def load_option_cases() -> dict[str, object]:
    return json.loads(
        (DECISION_SUPPORT_FIXTURES / "option_cases.v1.json").read_text(encoding="utf-8")
    )


def build_evidence_state(case: dict[str, object]) -> EvidenceWorldState:
    case_id = str(case["id"])
    disaster = Disaster(str(case["disaster"]))
    country = COUNTRIES.get_by_alpha3(str(case["country_code"]))
    if country is None:
        raise ValueError(f"Decision-support fixture country is unknown: {case_id}")
    event_time = datetime(2026, 8, 11, 6, tzinfo=UTC)
    event_source = SourceReference(
        source_id=f"event-{case_id}",
        publisher="Frozen event source",
        title=f"Event {case_id}",
        canonical_url=f"https://events.example/{case_id}",
        published_at=event_time,
        updated_at=None,
        retrieved_at=DECISION_SUPPORT_NOW,
        authority=SourceAuthority.SCIENTIFIC_AUTHORITY,
    )
    event = DisasterEvent(
        event_id=case_id,
        disaster=disaster,
        location=country.canonical_name,
        country=country,
        event_time=event_time,
        source=event_source,
        measurements=(
            ()
            if case.get("magnitude") is None
            else (
                EventMeasurement(
                    MeasurementKind.MAGNITUDE,
                    float(case["magnitude"]),
                    source=event_source,
                ),
            )
        ),
    )
    physical_event = (
        default_event_policy_registry()
        .for_disaster(disaster)
        .identify((event,))
        .physical_events[0]
    )
    raw_reports = case.get("reports")
    if raw_reports is None:
        raw_reports = (
            []
            if not case.get("facts")
            else [{"source_id": f"report-{case_id}", "facts": case["facts"]}]
        )
    if not isinstance(raw_reports, list):
        raise ValueError(f"Decision-support fixture reports are invalid: {case_id}")
    reports: list[SituationReport] = []
    for raw_report in raw_reports:
        if not isinstance(raw_report, dict):
            raise ValueError(f"Decision-support fixture report is invalid: {case_id}")
        source_id = str(raw_report["source_id"])
        source_time = DECISION_SUPPORT_NOW - timedelta(
            hours=float(raw_report.get("hours_ago", 0))
        )
        source = SourceReference(
            source_id=source_id,
            publisher=f"Authority {source_id}",
            title=f"Situation {source_id}",
            canonical_url=f"https://reports.example/{case_id}/{source_id}",
            published_at=source_time,
            updated_at=None,
            retrieved_at=DECISION_SUPPORT_NOW,
            authority=SourceAuthority.NATIONAL_AUTHORITY,
        )
        raw_facts = raw_report["facts"]
        if not isinstance(raw_facts, list):
            raise ValueError(f"Decision-support fixture facts are invalid: {case_id}")
        facts = tuple(
            ReportedFact(
                category=str(fact["category"]),
                label=str(fact["category"]).replace("_", " ").title(),
                value=str(fact["value"]),
                status=FactStatus(str(fact.get("status", "confirmed"))),
                source=source,
                event_id=case_id,
                claim_id=str(fact["category"]),
            )
            for fact in raw_facts
        )
        reports.append(
            SituationReport(
                source=source,
                narrative="Frozen decision-support packet.",
                facts=facts,
                event_id=case_id,
                disaster=disaster,
                country_codes=(country.alpha3_code,),
            )
        )
    return build_evidence_world_state(
        event,
        tuple(reports),
        evaluated_at=DECISION_SUPPORT_NOW,
        physical_event=physical_event,
    )


def build_decision_products(
    case: dict[str, object],
) -> tuple[
    EvidenceWorldState,
    tuple[HypothesisArtifact, ...],
    IncidentPriorityAssessment,
    InternalTriageDecision,
    DecisionSupportArtifact,
]:
    state = build_evidence_state(case)
    hypotheses = HypothesisGenerator().generate(state)
    priority = IncidentPriorityRanker().assess(state)
    triage = TriageAutonomyPolicy().decide(priority)
    artifact = DecisionOptionGenerator().generate(state, hypotheses, priority, triage)
    return state, hypotheses, priority, triage, artifact
