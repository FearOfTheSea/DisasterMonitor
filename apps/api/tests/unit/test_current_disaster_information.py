from datetime import UTC, datetime

import pytest
from conftest import FakeDisasterInformationProvider, FakeLanguageModel

from disaster_monitor.application.dto import (
    DisasterInformationItem,
    DisasterInformationResult,
)
from disaster_monitor.application.services.current_disaster_information import (
    build_disaster_information_query,
    requires_current_disaster_information,
)
from disaster_monitor.application.use_cases.answer_map_question import AnswerMapQuestion

VIETNAMESE_REQUEST = (
    "Thử xem dùng hệ thống này để cập nhật thông tin mới nhất về thiệt hại "
    "tại Nhật Bản xem có đc k nhé"
)


def test_routes_the_requested_vietnamese_japan_damage_question() -> None:
    assert requires_current_disaster_information(VIETNAMESE_REQUEST)
    assert requires_current_disaster_information(
        "Latest earthquake damage and casualties in Japan"
    )
    assert requires_current_disaster_information("日本の地震被害の最新情報")
    assert not requires_current_disaster_information("Giải thích động đất là gì")
    assert build_disaster_information_query(VIETNAMESE_REQUEST) == (
        "Japan earthquake latest damage casualties injuries official updates"
    )


@pytest.mark.asyncio
async def test_use_case_adds_attributed_current_evidence_to_the_model_prompt() -> None:
    information = DisasterInformationResult(
        query="Japan earthquake latest damage casualties injuries official updates",
        retrieved_at=datetime(2026, 8, 5, 7, 0, tzinfo=UTC),
        items=(
            DisasterInformationItem(
                title="Authorities publish a preliminary damage update",
                source="NHK",
                published_at=datetime(2026, 8, 5, 6, 30, tzinfo=UTC),
                url="https://example.test/nhk-report",
                summary="Officials reported preliminary figures; assessment continues.",
            ),
        ),
    )
    provider = FakeDisasterInformationProvider(result=information)
    model = FakeLanguageModel(
        response_text="<think>hidden</think>Final: Đã tổng hợp nguồn mới nhất."
    )
    use_case = AnswerMapQuestion(model, provider)

    answer = await use_case.execute(VIETNAMESE_REQUEST, "browser-session")

    assert answer.message == "Đã tổng hợp nguồn mới nhất."
    assert provider.queries == [
        "Japan earthquake latest damage casualties injuries official updates"
    ]
    system_prompt = model.requests[0].messages[0].content
    user_prompt = model.requests[0].messages[1].content
    assert "only allowed" in system_prompt
    assert "source for time-sensitive facts" in system_prompt
    assert "answer in the language" in system_prompt
    assert "Retrieved at: 2026-08-05T07:00:00+00:00" in user_prompt
    assert "source: NHK" in user_prompt
    assert "https://example.test/nhk-report" in user_prompt
    assert VIETNAMESE_REQUEST in user_prompt


@pytest.mark.asyncio
async def test_provider_failure_forces_an_explicit_unverified_context() -> None:
    provider = FakeDisasterInformationProvider(error=ConnectionError("offline"))
    model = FakeLanguageModel(response_text="Không thể xác minh dữ liệu mới nhất.")
    use_case = AnswerMapQuestion(model, provider)

    answer = await use_case.execute(VIETNAMESE_REQUEST)

    assert answer.message == "Không thể xác minh dữ liệu mới nhất."
    prompt = model.requests[0].messages[1].content
    assert "Status: unavailable" in prompt
    assert "Do not answer from model memory" in prompt


@pytest.mark.asyncio
async def test_non_current_question_does_not_call_the_provider() -> None:
    provider = FakeDisasterInformationProvider(error=AssertionError("must not run"))
    model = FakeLanguageModel()
    use_case = AnswerMapQuestion(model, provider)

    await use_case.execute("Động đất hình thành như thế nào?")

    assert provider.queries == []
    assert "Status: not requested" in model.requests[0].messages[1].content
