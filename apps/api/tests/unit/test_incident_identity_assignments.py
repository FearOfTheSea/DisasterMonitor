import pytest

from disaster_monitor.application.incidents.identity_assignments import (
    IncidentIdentityAssignments,
)
from disaster_monitor.application.incidents.models import (
    ActiveIncident,
    ActiveIncidentsSnapshot,
)
from disaster_monitor.domain.disaster import Disaster, ProviderTier

from .active_incidents_support import NOW, _source


class Store:
    def __init__(self):
        self.raw = None

    def read(self):
        return self.raw

    async def write(self, content):
        self.raw = content


def row(event_id, physical, aliases):
    source = _source("quakes", NOW)
    return ActiveIncident(
        event_id,
        Disaster.EARTHQUAKE,
        None,
        "Offshore",
        NOW,
        None,
        (),
        aliases,
        ProviderTier.PRIMARY,
        source.authority,
        source,
        physical_event_id=physical,
    )


def snapshot(*rows):
    return ActiveIncidentsSnapshot(NOW, rows, (), (), snapshot_version="fixture")


async def test_unique_alias_preserves_physical_id_and_link_across_restart():
    store = Store()
    registry = IncidentIdentityAssignments(store)
    original = row("usgs:1", "physical:original", ("usgs:1",))
    await registry.stabilize(snapshot(original))
    restarted = IncidentIdentityAssignments(store)
    replacement = row("gdacs:eq:1", "physical:replacement", ("usgs:1", "gdacs:eq:1"))
    updated = await restarted.stabilize(snapshot(replacement))
    assert updated.incidents[0].physical_event_id == "physical:original"
    assert restarted.lookup("usgs:1", now=NOW).event_id == "gdacs:eq:1"


async def test_split_cluster_makes_old_link_ambiguous():
    store = Store()
    registry = IncidentIdentityAssignments(store)
    await registry.stabilize(
        snapshot(row("usgs:1", "physical:old", ("usgs:1", "gdacs:eq:2")))
    )
    updated = await registry.stabilize(
        snapshot(
            row("usgs:1", "physical:a", ("usgs:1",)),
            row("gdacs:eq:2", "physical:b", ("gdacs:eq:2",)),
        )
    )
    assert {item.physical_event_id for item in updated.incidents} == {
        "physical:a",
        "physical:b",
    }
    with pytest.raises(ValueError, match="ambiguous"):
        registry.lookup("physical:old", now=NOW)
