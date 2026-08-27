"""Wildfire event equivalence policy."""

from datetime import timedelta

from disaster_monitor.application.services.event_policies.default import (
    CrossProviderGeoTemporalEventPolicy,
)


class WildfireEventPolicy(CrossProviderGeoTemporalEventPolicy):
    """Conservatively reconcile EONET and GDACS observations of one wildfire."""

    source_pair = frozenset(("nasa-eonet-wildfires", "gdacs-wildfires"))
    maximum_time_delta = timedelta(hours=72)
    maximum_distance_km = 25.0
