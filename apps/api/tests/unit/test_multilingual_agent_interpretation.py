import pytest

from disaster_monitor.application.agent.models import (
    DisasterTaskDraft,
    InformationNeed,
    InvestigationPlan,
    OutputModality,
    TaskKind,
    ValidationStatus,
)
from disaster_monitor.application.agent.runtime import DisasterAgentRuntime
from disaster_monitor.application.agent.task_normalization import (
    validate_disaster_task,
)
from disaster_monitor.application.services.disaster_query_parser import (
    DisasterQueryParser,
)
from disaster_monitor.domain.disaster import Disaster
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)

CATALOG = StaticCountryCatalog()


def canonical_draft(
    *,
    task_kind: TaskKind = TaskKind.INVESTIGATION,
    need: InformationNeed = InformationNeed.EVENT_OVERVIEW,
    response_language: str = "en",
    explicit: bool = False,
    country_code: str | None = "JPN",
) -> DisasterTaskDraft:
    return DisasterTaskDraft(
        disaster_related=task_kind is not TaskKind.NON_DISASTER,
        current_or_event_specific=task_kind is TaskKind.INVESTIGATION,
        information_needs=(need.value,),
        output_modalities=(
            OutputModality.FOCUSED_FACT.value
            if need is InformationNeed.FATALITIES
            else OutputModality.TEXT.value,
        ),
        task_kind=task_kind,
        disaster=(
            Disaster.EARTHQUAKE if task_kind is not TaskKind.NON_DISASTER else None
        ),
        country_code=country_code,
        country_name="Japan" if country_code == "JPN" else None,
        requested_response_language=response_language,
        response_language_explicit=explicit,
        canonical=True,
    )


@pytest.mark.parametrize(
    "question",
    (
        "What is the latest earthquake in Japan?",
        "Thông tin động đất mới nhất ở Nhật Bản là gì?",
        "日本で現在発生している地震について教えてください。",
        "일본의 현재 지진 상황을 알려 주세요.",
        "日本の現在の地震について教えてください。",
    ),
)
@pytest.mark.asyncio
async def test_canonical_interpretation_does_not_parse_surface_language(
    question: str,
) -> None:
    class NoTextParser:
        def parse(self, text: str):
            raise AssertionError("canonical interpretation must not parse raw text")

    class Interpreter:
        async def interpret(self, text: str) -> DisasterTaskDraft:
            return canonical_draft()

        async def propose_plan(self, task, tool_descriptions):
            return InvestigationPlan("empty", task.question, ())

        async def review_progress(self, task, completed_steps):
            raise AssertionError("empty canonical plan needs no review")

    runtime = DisasterAgentRuntime(
        country_catalog=CATALOG,
        query_parser=NoTextParser(),
        tool_registry=type("Tools", (), {"names": (), "descriptions": ()})(),
        agent_model=Interpreter(),
    )

    state = await runtime.run(question)

    assert state.task.kind is TaskKind.INVESTIGATION
    assert state.task.disaster is Disaster.EARTHQUAKE
    assert state.task.country is not None
    assert state.task.country.alpha3_code == "JPN"
    assert state.task.information_needs == (InformationNeed.EVENT_OVERVIEW,)
    assert state.task.output_modalities == (OutputModality.TEXT,)


def test_canonical_focused_need_and_language_are_validated_without_question_terms() -> (
    None
):
    task = validate_disaster_task(
        "語言完全不作為應用解析詞彙。",
        canonical_draft(
            need=InformationNeed.FATALITIES,
            response_language="zh",
            explicit=True,
        ),
        country_catalog=CATALOG,
        query_parser=DisasterQueryParser(CATALOG),
    )

    assert task.validation_status is ValidationStatus.VALID
    assert task.information_needs == (InformationNeed.FATALITIES,)
    assert OutputModality.FOCUSED_FACT in task.output_modalities
    assert task.response_language == "zh"
    assert task.response_language_explicit is True


def test_general_knowledge_is_delegated_from_canonical_intent() -> None:
    task = validate_disaster_task(
        "質問の表面言語を読まず一般知識として委譲する。",
        canonical_draft(task_kind=TaskKind.GENERAL_KNOWLEDGE, country_code=None),
        country_catalog=CATALOG,
        query_parser=DisasterQueryParser(CATALOG),
    )

    assert task.kind is TaskKind.GENERAL_KNOWLEDGE
    assert task.requires_evidence is False


def test_invented_or_unsupported_geography_fails_closed() -> None:
    task = validate_disaster_task(
        "invented geography",
        canonical_draft(country_code="ZZZ"),
        country_catalog=CATALOG,
        query_parser=DisasterQueryParser(CATALOG),
    )

    assert task.validation_status is ValidationStatus.CATALOG_LIMITATION
    assert task.country is None


@pytest.mark.asyncio
async def test_interpreter_failure_uses_safe_legacy_fallback() -> None:
    class FailingInterpreter:
        async def interpret(self, question: str):
            raise ValueError("interpreter unavailable")

        async def propose_plan(self, task, tool_descriptions):
            return InvestigationPlan("empty", task.question, ())

        async def review_progress(self, task, completed_steps):
            raise AssertionError("failed interpretation skips model review")

    class Tools:
        names = ()
        descriptions = ()

    runtime = DisasterAgentRuntime(
        country_catalog=CATALOG,
        query_parser=DisasterQueryParser(CATALOG),
        tool_registry=Tools(),
        agent_model=FailingInterpreter(),
    )

    state = await runtime.run("Latest earthquake information in Japan.")

    assert state.task.validation_status is ValidationStatus.VALID
    assert state.task.disaster is Disaster.EARTHQUAKE


def test_model_cannot_inject_an_unsupported_disaster_value() -> None:
    task = validate_disaster_task(
        "unsupported disaster",
        DisasterTaskDraft(
            disaster_related=True,
            current_or_event_specific=True,
            task_kind=TaskKind.INVESTIGATION,
            disaster="meteor",  # type: ignore[arg-type]
            country_code="JPN",
            canonical=True,
        ),
        country_catalog=CATALOG,
        query_parser=DisasterQueryParser(CATALOG),
    )

    assert task.validation_status is ValidationStatus.CLARIFICATION_REQUIRED
    assert task.disaster is None


def test_model_cannot_invent_an_event_discriminator() -> None:
    task = validate_disaster_task(
        "Latest earthquake in Japan.",
        DisasterTaskDraft(
            disaster_related=True,
            current_or_event_specific=True,
            task_kind=TaskKind.INVESTIGATION,
            disaster=Disaster.EARTHQUAKE,
            country_code="JPN",
            country_name="Japan",
            event_discriminators=("magnitude:9.9",),
            canonical=True,
        ),
        country_catalog=CATALOG,
        query_parser=DisasterQueryParser(CATALOG),
    )

    assert task.validation_status is ValidationStatus.CLARIFICATION_REQUIRED
    assert task.query is None
