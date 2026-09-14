# ADR 0001: Evidence-native, local-first workstation

## Status

Accepted — 2026-09-13.

## Decision

DisasterMonitor is an evidence-native, local-first disaster intelligence
workstation built on free, open, public, self-hosted, or free-account data
entitlements. The product's differentiator is inspectable evidence: operators
can see what is happening, which independent sources support it, what changed,
what is unknown or unavailable, which spatial context intersects the event, and
why a report claim was produced.

The local model is an interface and reasoning aid. It never creates current
facts, changes source authority, fills coverage gaps, or substitutes for a
stored observation.

## Scope contract

The following are explicit non-goals for the current product boundary:

- issuing public warnings;
- issuing evacuation directives;
- placing resource or response orders;
- promoting model-created facts into evidence.

Every new feature must strengthen at least one of evidence inspection,
monitoring resilience, spatial context, or interoperability. A feature that
requires a paid API as a production dependency requires a new ADR and is
outside this contract.

## Consequences

Provider rights, source snapshots, freshness, identity, coverage gaps, and
derived imagery must remain inspectable and versioned. Empty scans are not
evidence that no disaster exists. Warnings, forecasts, imagery observations,
humanitarian reports, and analytical/model outputs retain their own typed
roles instead of being flattened into physical-event truth.
