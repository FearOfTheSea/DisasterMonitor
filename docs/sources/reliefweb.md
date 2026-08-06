# ReliefWeb supplementary reports

Configured supplementary humanitarian situation reporting from ReliefWeb. It is not
event verification and not an official national-total source. Queries use normalized
country, hazard, event location, and bounded created dates; JMA/USGS IDs are not
mandatory terms. Sanitized narrative and recognized facts remain preliminary
humanitarian-aggregator evidence. ReliefWeb-local IDs are not compared with JMA/USGS
IDs; correlation uses hazard, country, occurrence time, location, magnitude when
present, and only comparable IDs. Missing configuration, malformed records, transport
failures, and empty results remain explicit. Upstream duplication and exact accuracy,
licensing, latency, and availability guarantees are unknown. Tests: realistic local-ID,
query, sanitization, and reconciliation regressions. Never promote this source to event
discovery or official totals.
