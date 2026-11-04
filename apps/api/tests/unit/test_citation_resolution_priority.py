"""Citation priority changes inspection order, not inclusion or publisher facts."""

import pytest

from disaster_monitor.domain.collection_retrieval_priority import (
    citation_resolution_priority,
)


def test_specific_disaster_account_precedes_unallocated_death_and_recovery_hints():
    strongest = citation_resolution_priority("Three people killed in overnight flood")
    unallocated = citation_resolution_priority("Football player dies after collision")
    retrospective = citation_resolution_priority("Flood survivors mark anniversary")
    unfamiliar = citation_resolution_priority("Local families describe what happened")
    assert strongest > unallocated > retrospective > unfamiliar


@pytest.mark.parametrize(
    "title",
    [
        "Flood could kill thousands, researchers warn",
        "Flood kills 200 cattle",
        "No deaths reported after earthquake",
        "Flood preparedness exercise simulates three deaths",
    ],
)
def test_nonhuman_negated_and_hypothetical_hints_do_not_get_specific_account_rank(
    title,
):
    assert citation_resolution_priority(title) < citation_resolution_priority(
        "Three people killed in overnight flood"
    )
