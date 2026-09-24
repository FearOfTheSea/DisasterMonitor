"""The live-case scorer must keep misses distinct from honest coverage gaps."""

from disaster_monitor.evaluation.local_assistant_e2e import score_case

CASE = {
    "id": "alaska-earthquake",
    "expected_event_id": "usgs:attkscoz",
    "source_url_contains": "attkscoz",
    "requested_place": "Nikolski",
}


def test_matching_event_requires_source_and_place_attribution() -> None:
    response = {
        "response_type": "current_disaster",
        "selected_event": {
            "event_id": "usgs:attkscoz",
            "location": "84 km SSW of Nikolski, Alaska",
        },
        "sources": [
            {
                "canonical_url": "https://earthquake.usgs.gov/earthquakes/eventpage/attkscoz"
            }
        ],
    }

    assert score_case(CASE, response) == "verified_event"


def test_romanized_place_matches_verified_accented_place() -> None:
    case = {**CASE, "requested_place": "Nghệ An"}
    response = {
        "response_type": "current_disaster",
        "selected_event": {
            "event_id": "usgs:attkscoz",
            "location": "Nghe An Province, Vietnam",
        },
        "sources": [{"canonical_url": "https://example.test/attkscoz"}],
    }

    assert score_case(case, response) == "verified_event"


def test_country_candidate_is_partial_even_when_honestly_reported() -> None:
    response = {
        "response_type": "current_disaster_place_unverified",
        "selected_event": None,
        "sources": [{"canonical_url": "https://example.test/attkscoz"}],
        "investigation": {"place_candidate_count": 1},
    }

    assert score_case(CASE, response) == "honest_place_gap"


def test_place_gap_without_linked_candidate_is_not_counted_as_honest() -> None:
    response = {
        "response_type": "current_disaster_place_unverified",
        "selected_event": None,
        "sources": [],
        "investigation": {"place_candidate_count": 0},
    }

    assert score_case(CASE, response) == "unattributed_place_gap"


def test_wrong_event_and_missing_source_are_not_counted_as_hits() -> None:
    wrong = {
        "response_type": "current_disaster",
        "selected_event": {"event_id": "usgs:another", "location": "Nikolski"},
        "sources": [{"canonical_url": "https://example.test/another"}],
    }
    missing_source = {
        **wrong,
        "selected_event": {"event_id": "usgs:attkscoz", "location": "Nikolski"},
    }

    assert score_case(CASE, wrong) == "wrong_event"
    assert score_case(CASE, missing_source) == "unattributed_event"


def test_expected_event_fails_when_answer_includes_other_region_impact() -> None:
    case = {**CASE, "answer_excludes": ["Phu Tho Province"]}
    response = {
        "response_type": "current_disaster",
        "selected_event": {
            "event_id": "usgs:attkscoz",
            "location": "Nikolski, Alaska",
        },
        "sources": [{"canonical_url": "https://example.test/attkscoz"}],
        "answer": "Reported houses damaged — Phu Tho Province: 153",
    }

    assert score_case(case, response) == "wrong_place_impact"
