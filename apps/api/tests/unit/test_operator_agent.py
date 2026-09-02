import json

import pytest

from disaster_monitor.application.agent.models import (
    DisasterTaskDraft,
    TaskKind,
    ValidatedDisasterTask,
)
from disaster_monitor.application.agent.operator_actions import (
    OPERATOR_ACTION_IDS,
    AutomaticOperatorAction,
    IncidentWatchOperatorAction,
    resolve_operator_actions,
)
from disaster_monitor.application.agent.task_normalization import (
    is_obvious_non_disaster_map_question,
    validate_disaster_task,
)
from disaster_monitor.application.assistant_message_payload import (
    assistant_answer_from_payload,
    assistant_message_payload,
)
from disaster_monitor.application.disaster import GeographicScope
from disaster_monitor.application.dto import (
    AssistantAnswer,
    ModelReadiness,
    ModelRequest,
    ModelResponse,
)
from disaster_monitor.application.services.disaster_query_parser import (
    DisasterQueryParser,
)
from disaster_monitor.domain.conversation import AssistantMessagePayload
from disaster_monitor.domain.disaster import Disaster
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)
from disaster_monitor.infrastructure.llm.structured_agent_model import (
    StructuredAgentModel,
)

CATALOG = StaticCountryCatalog()
PARSER = DisasterQueryParser(CATALOG)


def investigation_task(*action_ids: str, country: bool = True) -> ValidatedDisasterTask:
    return ValidatedDisasterTask(
        question="Latest earthquake in Japan",
        kind=TaskKind.INVESTIGATION,
        requires_evidence=True,
        disaster=Disaster.EARTHQUAKE,
        country=CATALOG.get_by_alpha3("JPN") if country else None,
        operator_action_ids=action_ids,
    )


def test_operator_v1_vocabulary_is_explicit_and_bounded() -> None:
    assert OPERATOR_ACTION_IDS == frozenset(
        {
            "open:findings",
            "open:sources",
            "open:watches",
            "open:operations",
            "time:1h",
            "time:6h",
            "time:24h",
            "time:48h",
            "time:7d",
            "show-layer:active-incidents",
            "show-layer:satellite-imagery",
            "show-layer:cop-evidence",
            "show-layer:cyclone-supplemental",
            "show-layer:authoritative-weather-alerts",
            "show-layer:compound-correlations",
            "create-watch:900",
            "create-watch:1800",
            "create-watch:3600",
            "create-watch:21600",
            "create-watch:86400",
        }
    )


def test_resolves_automatic_actions_to_typed_bounded_values() -> None:
    actions = resolve_operator_actions(
        investigation_task("open:operations", "time:24h", "show-layer:active-incidents")
    )

    assert actions == (
        AutomaticOperatorAction(
            action_id="open:operations",
            action_type="open_panel",  # type: ignore[arg-type]
            risk="automatic",  # type: ignore[arg-type]
            operation="open",  # type: ignore[arg-type]
            target="panel",  # type: ignore[arg-type]
            value="operations",
            user_safe_label="Open Evidence Operations",
        ),
        AutomaticOperatorAction(
            action_id="time:24h",
            action_type="set_time_window",  # type: ignore[arg-type]
            risk="automatic",  # type: ignore[arg-type]
            operation="set",  # type: ignore[arg-type]
            target="time_window",  # type: ignore[arg-type]
            value="24h",
            user_safe_label="Show a 24-hour display window",
        ),
        AutomaticOperatorAction(
            action_id="show-layer:active-incidents",
            action_type="show_layer",  # type: ignore[arg-type]
            risk="automatic",  # type: ignore[arg-type]
            operation="show",  # type: ignore[arg-type]
            target="map_layer",  # type: ignore[arg-type]
            value="active-incidents",
            user_safe_label="Show Active incidents",
        ),
    )


def test_invalid_candidates_fail_closed_only_for_actions() -> None:
    task = investigation_task("open:operations", "open:operations", "unknown")
    assert resolve_operator_actions(task) == ()
    assert (
        resolve_operator_actions(investigation_task(*tuple(OPERATOR_ACTION_IDS)[:5]))
        == ()
    )


def test_watch_proposal_uses_only_canonical_normalized_task_scope() -> None:
    actions = resolve_operator_actions(investigation_task("create-watch:1800"))

    assert len(actions) == 1
    action = actions[0]
    assert isinstance(action, IncidentWatchOperatorAction)
    assert action.disaster.value == "earthquake"
    assert action.scope.kind.value == "country"
    assert action.scope.country_code == "JPN"
    assert action.scope.country_name == "Japan"
    assert action.refresh_interval_seconds == 1800
    assert action.user_safe_label == "Create a 30-minute earthquake watch for Japan"


def test_watch_proposal_is_discarded_without_exact_supported_scope() -> None:
    assert (
        resolve_operator_actions(investigation_task("create-watch:900", country=False))
        == ()
    )
    worldwide = ValidatedDisasterTask(
        question="Latest earthquake worldwide",
        kind=TaskKind.INVESTIGATION,
        requires_evidence=True,
        disaster=Disaster.EARTHQUAKE,
        geographic_scope=GeographicScope.WORLDWIDE,
        operator_action_ids=("create-watch:86400",),
    )
    actions = resolve_operator_actions(worldwide)
    assert isinstance(actions[0], IncidentWatchOperatorAction)
    assert actions[0].scope.kind.value == "worldwide"
    assert actions[0].scope.country_code is None
    assert actions[0].scope.country_name is None


def test_task_normalization_carries_only_valid_operator_candidates() -> None:
    draft = DisasterTaskDraft(
        disaster_related=True,
        current_or_event_specific=True,
        task_kind=TaskKind.INVESTIGATION,
        disaster=Disaster.EARTHQUAKE,
        country_code="JPN",
        country_name="Japan",
        geographic_scope=GeographicScope.COUNTRY,
        information_needs=("event_overview",),
        output_modalities=("text",),
        operator_action_ids=("open:watches",),
        canonical=True,
    )
    task = validate_disaster_task(
        "Latest earthquake in Japan",
        draft,
        country_catalog=CATALOG,
        query_parser=PARSER,
    )
    assert task.operator_action_ids == ("open:watches",)


def test_explicit_layer_request_uses_structured_interpretation_path() -> None:
    assert not is_obvious_non_disaster_map_question("Show the active incidents layer")


class OneCallModel:
    def __init__(self, response: str) -> None:
        self.response = response
        self.requests: list[ModelRequest] = []

    async def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return ModelResponse(self.response, "fake-agent")

    async def check_readiness(self) -> ModelReadiness:
        return ModelReadiness(True, True, "fake-agent")


@pytest.mark.asyncio
async def test_structured_interpretation_selects_ids_in_the_existing_call() -> None:
    response = {
        "task_kind": "investigation",
        "disaster": "earthquake",
        "country_code": "JPN",
        "country_name": "Japan",
        "geographic_scope": "country",
        "place_mentions": ["Japan"],
        "current_or_event_specific": True,
        "date_from": None,
        "date_to": None,
        "information_needs": ["event_overview"],
        "output_modalities": ["text"],
        "event_discriminators": [],
        "requested_response_language": "en",
        "response_language_explicit": False,
        "worldwide_selection": None,
        "clarification_question": None,
        "operator_action_ids": ["open:watches", "create-watch:900"],
    }
    model = OneCallModel(json.dumps(response))

    result = await StructuredAgentModel(model).interpret(
        "Open watches and monitor earthquakes in Japan every 15 minutes"
    )

    assert result.operator_action_ids == ("open:watches", "create-watch:900")
    assert len(model.requests) == 1
    assert "operator_action_ids" in model.requests[0].messages[1].content


@pytest.mark.asyncio
async def test_structured_interpretation_returns_no_actions_without_request() -> None:
    response = {
        "task_kind": "investigation",
        "disaster": "earthquake",
        "country_code": "JPN",
        "country_name": "Japan",
        "geographic_scope": "country",
        "place_mentions": ["Japan"],
        "current_or_event_specific": True,
        "date_from": None,
        "date_to": None,
        "information_needs": ["event_overview"],
        "output_modalities": ["text"],
        "event_discriminators": [],
        "requested_response_language": "en",
        "response_language_explicit": False,
        "worldwide_selection": None,
        "clarification_question": None,
        "operator_action_ids": [],
    }
    model = OneCallModel(json.dumps(response))

    result = await StructuredAgentModel(model).interpret(
        "What is the latest earthquake information for Japan?"
    )

    assert result.operator_action_ids == ()
    assert len(model.requests) == 1


def test_legacy_v1_assistant_payload_decodes_without_operator_actions() -> None:
    answer = AssistantAnswer("Previous answer", "conversation-1", "old-model")
    current = assistant_message_payload(answer)
    legacy_data = dict(current.data)
    legacy_data.pop("operator_actions")

    decoded = assistant_answer_from_payload(
        AssistantMessagePayload("assistant-answer.v1", legacy_data)
    )

    assert decoded is not None
    assert decoded.operator_actions == ()
