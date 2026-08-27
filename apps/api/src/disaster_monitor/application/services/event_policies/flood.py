"""Flood event equivalence policy."""

from datetime import timedelta

from disaster_monitor.application.services.event_policies.default import (
    CrossProviderGeoTemporalEventPolicy,
)


class FloodEventPolicy(CrossProviderGeoTemporalEventPolicy):
    """Conservatively reconcile GFM and GDACS observations of one flood."""

    source_pair = frozenset(("cems-gfm-floods", "gdacs-floods"))
    maximum_time_delta = timedelta(hours=72)
    maximum_distance_km = 25.0
