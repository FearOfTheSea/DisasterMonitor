from disaster_monitor.application.agent.investigation_cases import (
    CrossHazardAssessment,
    CrossHazardAssessmentStatus,
    InvestigationCaseArtifact,
    InvestigationCaseCountry,
    InvestigationCaseStatus,
    InvestigationTargetResult,
)
from disaster_monitor.application.agent.models import (
    AgentStatus,
    InformationNeed,
    InvestigationTarget,
    OutputModality,
)
from disaster_monitor.application.assistant_message_payload import (
    assistant_answer_from_payload,
    assistant_message_payload,
)
from disaster_monitor.application.disaster import DisasterQuery
from disaster_monitor.application.dto import AssistantAnswer
from disaster_monitor.domain.conversation import AssistantMessagePayload
from disaster_monitor.domain.disaster import Disaster
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)


def _case() -> InvestigationCaseArtifact:
    country = StaticCountryCatalog().get_by_alpha3("JPN")
    assert country is not None
    targets = tuple(
        InvestigationTarget(
            target_id=f"investigation-target:v1:JPN:{index}:{disaster.value}",
            disaster=disaster,
            country=country,
            query=DisasterQuery(
                disaster=disaster,
                country=country,
                time_intent="recent",
                focus=("event_overview",),
            ),
            information_needs=(InformationNeed.EVENT_OVERVIEW,),
            output_modalities=(OutputModality.TEXT,),
        )
        for index, disaster in enumerate(
            (Disaster.EARTHQUAKE, Disaster.LANDSLIDE), start=1
        )
    )
    first, second = targets
    return InvestigationCaseArtifact(
        case_id="investigation-case:v1:fixture",
        country=InvestigationCaseCountry.from_country(country),
        targets=(
            InvestigationTargetResult(
                first,
                AgentStatus.COMPLETED,
                None,
                (),
                (),
                (),
                False,
                "grounded_answer_composed",
            ),
            InvestigationTargetResult(
                second,
                AgentStatus.COVERAGE_UNAVAILABLE,
                None,
                (),
                ("No matching event.",),
                (),
                True,
                "coverage_unavailable",
            ),
        ),
        cross_hazard_assessment=CrossHazardAssessment(
            CrossHazardAssessmentStatus.INSUFFICIENT_EVIDENCE,
            "One branch did not establish a selected event.",
            "Spatial and temporal proximity does not establish causation.",
        ),
        correlations=(),
        status=InvestigationCaseStatus.PARTIAL,
        partial=True,
    )


def test_v3_payload_round_trips_the_bounded_case_artifact() -> None:
    payload = assistant_message_payload(
        AssistantAnswer(
            "Two-hazard report.",
            "conversation-1",
            "fixture-agent",
            investigation_case=_case(),
        )
    )

    decoded = assistant_answer_from_payload(payload)

    assert payload.schema_version == "assistant-answer.v3"
    assert decoded is not None
    assert decoded.investigation_case is not None
    assert decoded.investigation_case.case_id == "investigation-case:v1:fixture"
    assert (
        decoded.investigation_case.targets[1].status is AgentStatus.COVERAGE_UNAVAILABLE
    )


def test_v1_and_v2_payloads_decode_without_investigation_case_activity() -> None:
    current = assistant_message_payload(
        AssistantAnswer("Previous answer", "conversation-1", "old-model")
    )
    v2_data = dict(current.data)
    v2_data.pop("investigation_case")
    v2 = assistant_answer_from_payload(
        AssistantMessagePayload("assistant-answer.v2", v2_data)
    )
    v1_data = dict(current.data)
    v1_data.pop("operator_actions")
    v1_data.pop("investigation_case")
    v1 = assistant_answer_from_payload(
        AssistantMessagePayload("assistant-answer.v1", v1_data)
    )

    assert v1 is not None and v1.operator_actions == ()
    assert v2 is not None and v2.operator_actions == ()
    assert v1.investigation_case is None
    assert v2.investigation_case is None
