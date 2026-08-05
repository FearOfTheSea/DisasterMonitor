from datetime import date

import pytest
from conftest import FakeLanguageModel

from disaster_monitor.application.services.prompt_preparation import (
    normalize_question,
    prepare_model_request,
)
from disaster_monitor.application.use_cases.answer_map_question import AnswerMapQuestion
from disaster_monitor.domain.errors import InvalidQuestionError, ModelRuntimeError
from disaster_monitor.domain.models import MapQuestion, MapView


@pytest.mark.asyncio
async def test_use_case_normalizes_prompt_and_returns_stable_answer() -> None:
    model = FakeLanguageModel(
        response_text="<think>hidden</think>Final: General guidance."
    )
    use_case = AnswerMapQuestion(model)

    result = await use_case.execute(
        "  What   should I inspect?  ",
        conversation_id="browser-session",
        map_view=MapView(21.03, 105.85, 10),
    )

    assert result.message == "General guidance."
    assert result.conversation_id == "browser-session"
    assert result.model == "fake-qwen"
    assert model.requests[0].messages[0].role == "system"
    assert "no live weather" in model.requests[0].messages[0].content
    assert "center latitude 21.03000" in model.requests[0].messages[1].content
    assert "What should I inspect?" in model.requests[0].messages[1].content


def test_normalize_question_rejects_empty_and_oversized_text() -> None:
    with pytest.raises(InvalidQuestionError):
        normalize_question(" \n\t ")
    with pytest.raises(InvalidQuestionError):
        normalize_question("x" * 2_001)


def test_prompt_preparation_is_deterministic_without_map_context() -> None:
    question = MapQuestion("Explain the map", "session")

    request = prepare_model_request(question, current_date=date(2026, 8, 5))

    assert request == prepare_model_request(
        question,
        current_date=date(2026, 8, 5),
    )
    assert request.messages[1].content == (
        "Runtime date: 2026-08-05.\n"
        "Map view context: unavailable.\n"
        "CURRENT DISASTER INFORMATION EVIDENCE\n"
        "Status: not requested for this question.\n"
        "User question: Explain the map"
    )


@pytest.mark.asyncio
async def test_use_case_translates_unexpected_model_failures() -> None:
    model = FakeLanguageModel(error=ConnectionError("offline"))
    use_case = AnswerMapQuestion(model)

    with pytest.raises(ModelRuntimeError, match="local model runtime"):
        await use_case.execute("Is this a safe area?")
