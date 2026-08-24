from datetime import UTC, datetime, timedelta

from disaster_monitor.application.services.conversation_context import (
    MAX_HISTORY_CHARACTERS,
    MAX_HISTORY_MESSAGES,
    resolve_disaster_follow_up,
    select_bounded_history,
)
from disaster_monitor.domain.conversation import (
    ConversationMessage,
    ConversationRole,
)
from disaster_monitor.domain.memory import (
    MemoryAuthority,
    MemoryContextArtifact,
)
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)

NOW = datetime(2026, 8, 21, tzinfo=UTC)


def _catalog() -> StaticCountryCatalog:
    result = StaticCountryCatalog()
    result.activate_payload(
        {
            "metadata": {"version": "conversation-context-test"},
            "countries": [
                {
                    "alpha3": "THA",
                    "name": "Thailand",
                    "aliases": ["TH"],
                    "timezone": "Asia/Bangkok",
                    "bounds": [5.5, 20.5, 97.3, 105.7],
                    "polygons": [],
                },
                {
                    "alpha3": "VNM",
                    "name": "Vietnam",
                    "aliases": ["VN"],
                    "timezone": "Asia/Ho_Chi_Minh",
                    "bounds": [8.2, 23.4, 102.1, 109.5],
                    "polygons": [],
                },
            ],
        }
    )
    return result


def message(
    message_id: str,
    content: str,
    role: ConversationRole = ConversationRole.USER,
    conversation_id: str = "conversation-a",
) -> ConversationMessage:
    return ConversationMessage(
        message_id=message_id,
        conversation_id=conversation_id,
        role=role,
        content=content,
        created_at=NOW + timedelta(seconds=int(message_id.removeprefix("m"))),
    )


def test_newest_whole_messages_fit_message_and_character_bounds() -> None:
    history = tuple(
        message(
            f"m{index}",
            "x" * 1_000,
            ConversationRole.USER if index % 2 == 0 else ConversationRole.ASSISTANT,
        )
        for index in range(10)
    )

    selected = select_bounded_history(history)

    assert len(selected) <= MAX_HISTORY_MESSAGES
    assert sum(len(item.content) for item in selected) <= MAX_HISTORY_CHARACTERS
    assert [item.message_id for item in selected] == [
        "m4",
        "m5",
        "m6",
        "m7",
        "m8",
        "m9",
    ]
    assert list(selected) == sorted(selected, key=lambda item: item.created_at)


def test_histories_are_filtered_by_conversation_before_selection() -> None:
    history = (
        message("m1", "Conversation A", conversation_id="conversation-a"),
        message("m2", "Conversation B", conversation_id="conversation-b"),
        message("m3", "More A", conversation_id="conversation-a"),
    )

    selected = select_bounded_history(history, conversation_id="conversation-a")

    assert [item.content for item in selected] == ["Conversation A", "More A"]


def test_orphaned_leading_assistant_messages_are_excluded() -> None:
    history = (
        message("m1", "old user"),
        message("m2", "old answer", ConversationRole.ASSISTANT),
        message("m3", "too large user" * 1_000),
        message("m4", "new answer", ConversationRole.ASSISTANT),
    )

    selected = select_bounded_history(history, max_characters=15)

    assert selected == ()


def test_assistant_text_is_never_a_disaster_resolution_anchor() -> None:
    catalog = _catalog()
    history = (
        message(
            "m1",
            "The latest floods in Thailand are severe.",
            ConversationRole.ASSISTANT,
        ),
    )

    assert (
        resolve_disaster_follow_up(
            "What about Vietnam?", history, country_catalog=catalog
        )
        == "What about Vietnam?"
    )


def test_country_follow_up_inherits_disaster_but_not_anchor_country() -> None:
    catalog = _catalog()
    history = (message("m1", "What are the latest floods in Thailand?"),)

    resolved = resolve_disaster_follow_up(
        "What about Vietnam?", history, country_catalog=catalog
    )

    assert "flood" in resolved.lower()
    assert "Vietnam" in resolved
    assert "Thailand" not in resolved


def test_information_follow_up_inherits_disaster_and_country() -> None:
    catalog = _catalog()
    history = (message("m1", "What are the latest floods in Thailand?"),)

    resolved = resolve_disaster_follow_up(
        "What about fatalities there?", history, country_catalog=catalog
    )

    assert "flood" in resolved.lower()
    assert "Thailand" in resolved
    assert "fatalities" in resolved.lower()


def test_explicit_current_entities_override_inherited_context() -> None:
    catalog = _catalog()
    history = (message("m1", "What are the latest floods in Thailand?"),)

    resolved = resolve_disaster_follow_up(
        "What about earthquakes in Vietnam?", history, country_catalog=catalog
    )

    assert resolved == "What about earthquakes in Vietnam?"


def test_ambiguous_and_non_referential_turns_remain_unchanged() -> None:
    catalog = _catalog()
    history = (message("m1", "What are the latest floods in Thailand?"),)

    assert (
        resolve_disaster_follow_up(
            "Tell me about Vietnam.", history, country_catalog=catalog
        )
        == "Tell me about Vietnam."
    )
    assert (
        resolve_disaster_follow_up(
            "What about Thailand and Vietnam?", history, country_catalog=catalog
        )
        == "What about Thailand and Vietnam?"
    )


def test_long_term_memory_is_not_transcript_or_current_evidence() -> None:
    context = MemoryContextArtifact(
        context_id="memory-context:test",
        conversation_id="conversation-a",
        physical_event_id=None,
        records=(),
        created_at=NOW,
        total_characters=0,
        maximum_records=5,
        maximum_characters=1_500,
    )

    assert select_bounded_history(()) == ()
    assert context.authority is MemoryAuthority.HISTORICAL_CONTEXT
    assert context.may_satisfy_current_evidence is False
