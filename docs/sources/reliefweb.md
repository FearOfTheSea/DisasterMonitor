# ReliefWeb supplementary reports

ReliefWeb provides configured supplementary humanitarian situation reporting.

It is not event verification or an official national-total source.

Queries use normalized country, disaster, and bounded UTC ISO-8601 created dates.

Selected-event location and event-provider IDs are not mandatory free-text terms.
ReliefWeb’s `AND` query parser would otherwise discard valid reports with different
place wording.

Sanitized narrative and recognized facts remain preliminary humanitarian-aggregator
evidence.

The adapter requests report identity, structured disaster metadata, primary country,
classification, title, body, and publication fields.

Provider-local IDs are not compared with event-provider IDs.

Correlation uses disaster, country, occurrence time, location, magnitude when present,
and comparable IDs only.

Explicit magnitudes in report narratives remain correlation clues.

Never treat publication time as event time.

A report needs two independent event clues, or one same-namespace ID, to become matched
evidence.

Keep possible and unmatched reports out of trusted facts.

Keep missing configuration, malformed records, transport failures, and empty results
explicit.

Upstream duplication and exact accuracy, licensing, latency, and availability
guarantees are unknown.

Tests cover realistic local-ID, structured-scope, narrative-magnitude, sanitization,
and reconciliation regressions.

The v2 request asks only for fields accepted by the reports endpoint. Report location
metadata remains optional because it is not a selectable report field.

Never promote this source to event discovery or official totals.
