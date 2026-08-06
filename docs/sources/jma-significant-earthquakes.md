# JMA significant earthquakes

Official retained JMA warning-history discovery for significant Japan earthquakes.
The adapter reads a bounded HTML history and optional detail page without configuration.
History rows become typed events; details accept decimal and Japanese degree/minute
coordinates. The source is not treated as a complete earthquake catalog. Namespaced
JMA IDs and shared earthquake clustering apply. A failed detail page does not discard
a valid index event; malformed history and empty results remain diagnostics. Retention
criteria, latency, accuracy, and availability guarantees are unknown. Tests: significant
history and coordinate fixtures in `tests/integration/test_disaster_adapters.py`.
