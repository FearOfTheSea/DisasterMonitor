# ReliefWeb supplementary reports

Configured supplementary humanitarian situation reporting from ReliefWeb. It is not
event verification and not an official national-total source. Queries use normalized
country, hazard, and bounded UTC ISO-8601 created dates; selected-event location and
JMA/USGS IDs are not mandatory free-text terms because ReliefWeb's ``AND`` query parser
would otherwise discard valid reports that use different place wording. Sanitized
narrative and recognized facts remain preliminary humanitarian-aggregator evidence.
ReliefWeb-local IDs are not compared with JMA/USGS IDs; correlation uses hazard, country,
occurrence time, location, magnitude when present, and only comparable IDs. The adapter
requests report identity, structured disaster metadata, primary country, classification,
title, body, and publication fields. Explicit magnitudes in report narratives are retained
as correlation clues; publication time is never silently treated as event time. A report
needs two independent event clues (or a same-namespace ID) to become matched evidence;
possible and unmatched reports remain excluded from trusted facts. Missing
configuration, malformed records, transport failures, and empty results remain explicit.
Upstream duplication and exact accuracy, licensing, latency, and availability guarantees
are unknown. Tests: realistic local-ID, structured scope, narrative-magnitude,
sanitization, and reconciliation regressions. The v2 request only asks for fields accepted
by the reports endpoint; report location metadata remains optional because it is not a
selectable report field. See [event association acceptance criteria](../reliefweb-event-association-acceptance.md).
Never promote this source to event discovery or official totals.
