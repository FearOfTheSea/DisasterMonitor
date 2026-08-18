from disaster_monitor.application.agent.models import (
    DisasterTaskDraft,
    InformationNeed,
    OutputModality,
    TaskKind,
    ValidationStatus,
)
from disaster_monitor.application.agent.task_normalization import (
    deterministic_task_draft,
    disaster_safety_gate,
    validate_disaster_task,
    worldwide_disaster_query,
)
from disaster_monitor.application.services.disaster_query_parser import (
    DisasterQueryParser,
)
from disaster_monitor.domain.disaster import Hazard
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)

CATALOG = StaticCountryCatalog()
PARSER = DisasterQueryParser(CATALOG)


def validate(question: str, draft: DisasterTaskDraft | None = None):
    return validate_disaster_task(
        question,
        draft or deterministic_task_draft(question),
        country_catalog=CATALOG,
        query_parser=PARSER,
    )


def test_safety_gate_keeps_factual_disaster_requests_out_of_general_model() -> None:
    guarded = (
        "Any news about earthquakes in Vietnam?",
        "Any news about earthquakes in Venezuela?",
        "Any news about earthquakes in Thailand?",
        "Give me the latest earthquake information in Thailand.",
        "Latest earthquake in Japan and Venezuela.",
        "Latest earthquake.",
        "How many fatalities were caused by the earthquake in Japan?",
        "Show me pictures of the recent earthquake in Japan.",
        "Give me the latest flood information in Vietnam.",
        "Tell me about the August 5, 2026 earthquake in Japan.",
        "Tell me about the earthquake in Japan on 5/8/2026.",
    )
    assert all(disaster_safety_gate(question) for question in guarded)
    assert not disaster_safety_gate("What causes earthquakes?")
    assert not disaster_safety_gate("What is this map for?")


def test_news_request_uses_trusted_path_for_any_admitted_country() -> None:
    catalog = StaticCountryCatalog()
    catalog.activate_payload(
        {
            "metadata": {"version": "test-global"},
            "countries": [
                {
                    "alpha3": "THA",
                    "name": "Thailand",
                    "aliases": ["TH"],
                    "timezone": "Asia/Bangkok",
                    "bounds": [5.5, 20.5, 97.3, 105.7],
                    "polygons": [],
                }
            ],
        }
    )
    parser = DisasterQueryParser(catalog)
    question = "Any news about earthquakes in Thailand?"

    task = validate_disaster_task(
        question,
        deterministic_task_draft(question),
        country_catalog=catalog,
        query_parser=parser,
    )

    assert task.kind == TaskKind.INVESTIGATION
    assert task.validation_status == ValidationStatus.VALID
    assert task.requires_evidence
    assert task.country is not None and task.country.alpha3_code == "THA"
    assert task.query is not None and task.query.country is task.country


def test_worldwide_earthquake_scope_is_explicit_and_current_only() -> None:
    latest = worldwide_disaster_query("Any earthquake news worldwide?")
    strongest = worldwide_disaster_query(
        "What was the strongest earthquake across the world this week?"
    )

    assert latest is not None and latest.hazard is Hazard.EARTHQUAKE
    assert strongest == latest
    assert worldwide_disaster_query("Latest earthquake anywhere?") is not None
    assert worldwide_disaster_query("What causes earthquakes globally?") is None
    assert worldwide_disaster_query("Any flood news worldwide?") is not None


def test_explicit_dated_event_is_an_investigation_without_model_help() -> None:
    task = validate("Tell me about the August 5, 2026 earthquake in Japan.")

    assert task.kind == TaskKind.INVESTIGATION
    assert task.query is not None
    assert task.query.date_from is not None
    assert task.query.date_from.isoformat() == "2026-08-04T15:00:00+00:00"


def test_canonicalizes_supported_current_disaster_task_and_information_scope() -> None:
    task = validate(
        "How many fatalities were reported for the August 5, 2026 earthquake in Japan?"
    )

    assert task.kind == TaskKind.INVESTIGATION
    assert task.hazard == Hazard.EARTHQUAKE
    assert task.country is not None and task.country.alpha3_code == "JPN"
    assert task.information_needs == (InformationNeed.FATALITIES,)
    assert OutputModality.FOCUSED_FACT in task.output_modalities
    assert task.query is not None
    assert task.query.date_from is not None
    assert task.query.date_from.isoformat() == "2026-08-04T15:00:00+00:00"


def test_unknown_country_multiple_country_and_unsupported_hazard_are_retained() -> None:
    thailand = validate("Give me the latest earthquake information in Thailand.")
    multiple = validate("Compare the latest earthquakes in Japan and Venezuela.")
    flood = validate("Give me the latest flood information in Vietnam.")

    assert thailand.validation_status == ValidationStatus.CATALOG_LIMITATION
    assert thailand.unresolved_place == "Thailand"
    assert multiple.validation_status == ValidationStatus.CLARIFICATION_REQUIRED
    assert flood.validation_status == ValidationStatus.VALID
    assert flood.hazard == Hazard.FLOOD
    assert flood.country is not None and flood.country.alpha3_code == "VNM"


def test_model_cannot_invent_country_or_override_deterministic_disaster_gate() -> None:
    draft = DisasterTaskDraft(
        disaster_related=False,
        current_or_event_specific=False,
        hazard_mentions=("earthquake",),
        place_mentions=("Thailand", "TST"),
    )

    task = validate("Latest earthquake in Thailand.", draft)

    assert task.kind == TaskKind.INVESTIGATION
    assert task.validation_status == ValidationStatus.CATALOG_LIMITATION
    assert task.country is None


def test_general_knowledge_and_non_disaster_are_distinct() -> None:
    assert validate("What causes earthquakes?").kind == TaskKind.GENERAL_KNOWLEDGE
    assert validate("What is this map for?").kind == TaskKind.NON_DISASTER


def test_model_draft_cannot_expand_user_task_scope() -> None:
    map_question = (
        "What is this map for, and what can you infer from the current map center "
        "and zoom? Do not claim to see unavailable layers."
    )
    invented_disaster = DisasterTaskDraft(
        disaster_related=True,
        current_or_event_specific=True,
        hazard_mentions=("earthquake",),
        place_mentions=("Japan",),
        information_needs=("map_visualization",),
        output_modalities=("text", "map"),
    )
    expanded_investigation = DisasterTaskDraft(
        disaster_related=True,
        current_or_event_specific=True,
        hazard_mentions=("earthquake", "tsunami"),
        place_mentions=("Japan", "Venezuela"),
        information_needs=("event_overview", "images", "decision_support"),
        output_modalities=("text", "images", "map"),
    )

    map_task = validate(map_question, invented_disaster)
    investigation = validate("Latest earthquake in Japan.", expanded_investigation)

    assert map_task.kind == TaskKind.NON_DISASTER
    assert investigation.kind == TaskKind.INVESTIGATION
    assert investigation.hazard == Hazard.EARTHQUAKE
    assert investigation.country is not None
    assert investigation.country.alpha3_code == "JPN"
    assert investigation.information_needs == (InformationNeed.EVENT_OVERVIEW,)
    assert investigation.output_modalities == (OutputModality.TEXT,)


def test_image_request_records_capability_modality_without_faking_it() -> None:
    task = validate(
        "Show me pictures of the damage from the August 5, 2026 Japan earthquake."
    )
    assert InformationNeed.IMAGES in task.information_needs
    assert OutputModality.IMAGES in task.output_modalities


def test_multilingual_operational_needs_stay_on_the_evidence_path() -> None:
    cases = (
        ("Muertos del terremoto reciente en Japón.", InformationNeed.FATALITIES),
        (
            "Số người bị thương do động đất gần đây ở Việt Nam.",
            InformationNeed.INJURIES,
        ),
        ("日本の地震で行方不明の人はいますか？", InformationNeed.MISSING_PERSONS),
    )

    for question, need in cases:
        task = validate(question)
        assert task.kind == TaskKind.INVESTIGATION
        assert task.requires_evidence
        assert need in task.information_needs


def test_educational_and_transformative_prompts_do_not_claim_current_evidence() -> None:
    cases = (
        "What causes earthquakes in general?",
        "¿Qué es un terremoto?",
        "Động đất là gì?",
        "地震とは何ですか？",
        "Write a story about earthquake fatalities.",
        "Translate 'earthquake warning' into Spanish.",
    )

    assert all(not disaster_safety_gate(question) for question in cases)
