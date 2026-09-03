import base64

import httpx
import pytest
from assistant_http_fixtures import (
    CURRENT_PROMPT,
    build_current_service,
)
from conftest import FakeLanguageModel

from disaster_monitor.application.multimodal import (
    VisualModelPrediction,
    VisualModelReadiness,
)
from disaster_monitor.domain.disaster import (
    FactStatus,
)
from disaster_monitor.domain.multimodal import (
    DamageLevel,
    VisualAnalysisConfiguration,
)
from disaster_monitor.main import create_app


@pytest.mark.asyncio
async def test_fatality_request_is_focused_and_missing_is_not_zero() -> None:
    model = FakeLanguageModel(error=AssertionError("general model must not be called"))
    app = create_app(
        model=model,
        current_disaster_report=build_current_service(
            fact_category="fatalities",
            fact_label="Fatalities",
            fact_value="2",
        ),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/assistant",
            json={
                "question": (
                    "How many fatalities were reported for the August 5, 2026 "
                    "earthquake in Japan?"
                )
            },
        )

    body = response.json()
    assert "Fatalities: 2" in body["message"]
    assert [section["title"] for section in body["sections"]] == [
        "Focused answer",
        "Event details",
        "Conflicts and uncertainty",
        "Report freshness",
    ]
    assert body["investigation"]["information_needs"] == ["fatalities"]
    assert body["investigation"]["triage_priority"] == "critical"
    assert body["investigation"]["triage_action"] == "escalate_critical"
    assert body["investigation"]["triage_autonomy_mode"] == "human_in_the_loop"
    assert body["investigation"]["triage_requires_human_intervention"] is True
    assert model.requests == []


@pytest.mark.asyncio
async def test_decision_support_request_returns_advisory_evidence_bounded_options() -> (
    None
):
    model = FakeLanguageModel(error=AssertionError("general model must not be called"))
    app = create_app(model=model, current_disaster_report=build_current_service())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/assistant",
            json={
                "question": (
                    "What decision support options should analysts consider for the "
                    "current earthquake in Japan?"
                )
            },
        )

    assert response.status_code == 200
    body = response.json()
    decision_section = next(
        item for item in body["sections"] if item["title"] == "Decision support"
    )
    coordination_section = next(
        item for item in body["sections"] if item["title"] == "Specialist coordination"
    )
    assert "Advisory analytical options only" in decision_section["content"]
    assert "Continue approved-source monitoring" in body["message"]
    assert "Scenario mode:" in decision_section["content"]
    assert "Sensitivity:" in decision_section["content"]
    assert "Evidence gaps:" in decision_section["content"]
    assert "Recommendation layer (" in decision_section["content"]
    assert "Bounded decision state:" in decision_section["content"]
    assert (
        "without changing evidence or safety policy" in coordination_section["content"]
    )
    assert "Supervisor status: autonomous_complete" in coordination_section["content"]
    assert body["investigation"]["information_needs"] == ["decision_support"]
    assert body["investigation"]["decision_action"] in {
        "none",
        "continue_approved_monitoring",
        "compare_verified_updates",
    }
    assert body["investigation"]["decision_autonomy_mode"] in {
        "autonomous_internal",
        "advisory_only",
    }
    assert body["investigation"]["decision_state_revision"] in {0, 1}
    assert isinstance(body["investigation"]["decision_active_internal_states"], list)
    assert body["investigation"]["specialist_handoff_count"] == 2
    assert body["investigation"]["specialist_roles"] == [
        "evidence_reconciliation_specialist",
        "decision_analysis_specialist",
    ]
    assert body["investigation"]["collaboration_status"] == "completed"
    assert body["investigation"]["collaboration_finding_count"] >= 5
    assert body["investigation"]["collaboration_deadlock_count"] == 0
    assert body["investigation"]["collaboration_iterations"] == 1
    assert body["investigation"]["collaboration_fallback_reason"] is None
    assert body["investigation"]["coordination_supervision_id"].startswith(
        "coordination-supervision:"
    )
    assert (
        body["investigation"]["coordination_supervisor_status"] == "autonomous_complete"
    )
    assert body["investigation"]["coordination_sufficient"] is True
    assert body["investigation"]["coordination_missing_finding_keys"] == []
    assert (
        body["investigation"]["coordination_termination_reason"]
        == "sufficient_analytical_end_state"
    )
    assert body["investigation"]["coordination_final_rationale"]
    assert body["investigation"]["coordination_evidence_ids"]
    assert body["decision_support"]["advisory_only"] is True
    assert body["decision_support"]["facts"]
    assert all(
        fact["statement_type"] == "verified_fact"
        for fact in body["decision_support"]["facts"]
    )
    assert body["decision_support"]["estimates"][0]["statement_type"] == "estimate"
    assert body["investigation"]["coordination_analytical_focus"] in {
        "evidence_gaps",
        "material_conflicts",
        "multimodal_review",
        "routine_monitoring",
    }
    assert (
        body["investigation"]["coordination_analytical_parameter_set_id"]
        == "analytical-tuning:v3-governed"
    )
    assert (
        body["investigation"]["coordination_analytical_release_id"]
        == "analytical-tuning-release:v3-governed"
    )
    assert model.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("fact_status", "expected_statement_type"),
    (
        (FactStatus.PRELIMINARY, "preliminary_observation"),
        (FactStatus.ESTIMATED, "source_estimate"),
        (FactStatus.DISPUTED, "disputed_observation"),
    ),
)
async def test_decision_support_api_preserves_uncertain_source_status(
    fact_status: FactStatus,
    expected_statement_type: str,
) -> None:
    model = FakeLanguageModel(error=AssertionError("general model must not be called"))
    app = create_app(
        model=model,
        current_disaster_report=build_current_service(
            fact_category="injuries",
            fact_label="Injuries",
            fact_value="12",
            fact_status=fact_status,
        ),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/assistant",
            json={
                "question": (
                    "What decision support options should analysts consider for the "
                    "current earthquake in Japan?"
                )
            },
        )

    assert response.status_code == 200
    body = response.json()
    source_fact = next(
        fact
        for fact in body["decision_support"]["facts"]
        if fact["status"] == fact_status.value
    )
    estimate = body["decision_support"]["estimates"][0]
    assert source_fact["statement_type"] == expected_statement_type
    assert estimate["statement_type"] == "estimate"
    assert estimate["uncertain_evidence_ids"] == source_fact["evidence_ids"]
    decision_section = next(
        item for item in body["sections"] if item["title"] == "Decision support"
    )
    assert (
        f"[{expected_statement_type}; status={fact_status.value}]"
        in decision_section["content"]
    )
    assert model.requests == []


@pytest.mark.asyncio
async def test_image_request_runs_supported_text_path_and_reports_capability_gap() -> (
    None
):
    model = FakeLanguageModel(error=AssertionError("general model must not be called"))
    app = create_app(model=model, current_disaster_report=build_current_service())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/assistant",
            json={
                "question": (
                    "Show me pictures of the damage from the August 5, 2026 "
                    "Japan earthquake."
                )
            },
        )

    body = response.json()
    assert body["selected_event"]["event_id"] == "global-catalog:fixture-event"
    assert body["investigation"]["output_modalities"] == ["text", "images"]
    assert any(
        "image" in gap.lower() for gap in body["investigation"]["capability_gaps"]
    )
    assert "http" not in " ".join(body["investigation"]["capability_gaps"])
    assert model.requests == []


@pytest.mark.asyncio
async def test_invalid_agent_model_output_uses_default_plan_not_general_model() -> None:
    class BrokenAgentModel:
        calls = 0

        async def interpret(self, question):
            self.calls += 1
            raise ValueError("malformed structured output")

        async def propose_plan(self, task, tool_descriptions):
            self.calls += 1
            raise ValueError("unknown tool")

        async def review_progress(self, task, completed_steps):
            self.calls += 1
            raise ValueError("malformed review")

    agent_model = BrokenAgentModel()
    general = FakeLanguageModel(
        error=AssertionError("general model must not be called")
    )
    app = create_app(
        model=general,
        agent_model=agent_model,
        current_disaster_report=build_current_service(),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/assistant", json={"question": CURRENT_PROMPT}
        )

    body = response.json()
    assert response.status_code == 200
    assert body["selected_event"]["event_id"] == "global-catalog:fixture-event"
    assert len(body["investigation"]["actions"]) == 5
    assert agent_model.calls == 2
    assert general.requests == []
    forbidden = {"reasoning", "prompt", "raw_model_output", "chain_of_thought"}
    assert forbidden.isdisjoint(body["investigation"])


@pytest.mark.asyncio
async def test_operator_image_crosses_real_http_boundary_into_typed_cop() -> None:
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
        "+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )

    class FakeVisualAnalyzer:
        calls = 0

        async def analyze(self, request):
            self.calls += 1
            return VisualModelPrediction(
                damage_level=DamageLevel.MAJOR_DAMAGE,
                damage_confidence=0.86,
                damage_cues=("collapsed roof",),
                answer="major structural damage is visible",
                answerable=True,
                answer_confidence=0.81,
                answer_cues=("roof discontinuity",),
                configuration=VisualAnalysisConfiguration(
                    model_id="fake-vlm",
                    model_digest="fixture-digest",
                    adapter_version="fake-adapter-v1",
                    analysis_version="bounded-damage-vqa-v1",
                    prompt_version="dm-visual-analysis-v1",
                    preprocessing_version="original-png-jpeg-bytes-v1",
                    maximum_output_tokens=384,
                    temperature=0,
                    seed=7,
                ),
            )

        async def check_readiness(self):
            return VisualModelReadiness(
                True,
                True,
                "fake-vlm",
                "fixture-digest",
                "fake-adapter-v1",
                "dm-visual-analysis-v1",
                "original-png-jpeg-bytes-v1",
            )

    visual = FakeVisualAnalyzer()
    model = FakeLanguageModel(error=AssertionError("general model must not be called"))
    app = create_app(
        model=model,
        current_disaster_report=build_current_service(),
        visual_analyzer=visual,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/assistant",
            json={
                "question": (
                    "Analyze this image and map visible damage for the August 5, "
                    "2026 earthquake in Japan."
                ),
                "multimodal_assets": [
                    {
                        "content_base64": base64.b64encode(png).decode("ascii"),
                        "attribution": "Licensed operator test fixture",
                        "captured_at": "2026-08-05T11:00:00Z",
                        "footprint": {
                            "crs": "EPSG:4326",
                            "coordinates": [
                                [
                                    [136.8, 36.8],
                                    [137.2, 36.8],
                                    [137.2, 37.2],
                                    [136.8, 37.2],
                                    [136.8, 36.8],
                                ]
                            ],
                        },
                        "declared_disaster": "earthquake",
                        "declared_country_code": "JPN",
                        "capture_role": "post_event",
                        "dataset_id": "http-integration-fixture",
                        "license_name": "fixture-only",
                        "processing_level": "raw",
                    }
                ],
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert visual.calls == 1
    assert body["multimodal"]["evidence_world_state_version"]
    assert body["multimodal"]["observations"][0]["truth_status"] == "analytical"
    assert body["multimodal"]["assets"][0]["source"]["attribution"] == (
        "Licensed operator test fixture"
    )
    assert "content_base64" not in response.text
    cop = body["common_operational_picture"]
    assert cop["multimodal_state_version"] == body["multimodal"]["state_version"]
    feature = cop["layers"][0]["features"][0]
    assert feature["feature_type"] == "analytical"
    assert feature["authority"] == "analytical_generated"
    assert feature["source_asset_ids"] == [body["multimodal"]["assets"][0]["asset_id"]]
    assert feature["visual_observation_ids"]
    assert feature["uncertainty"]
    gaps = body["investigation"]["capability_gaps"]
    assert not any("image" in gap.casefold() for gap in gaps)
    assert not any("map layer" in gap.casefold() for gap in gaps)


@pytest.mark.asyncio
async def test_invalid_inline_image_encoding_is_rejected_before_investigation() -> None:
    model = FakeLanguageModel(error=AssertionError("model must not be called"))
    app = create_app(model=model, current_disaster_report=build_current_service())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/assistant",
            json={
                "question": CURRENT_PROMPT,
                "multimodal_assets": [
                    {
                        "content_base64": "%%%not-base64%%%",
                        "attribution": "Invalid fixture",
                    }
                ],
            },
        )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "Multimodal asset content must be valid base64."
    )
