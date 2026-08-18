# Current-disaster reporting

This page describes the bounded current-disaster path. See [agent-runtime.md](agent-runtime.md)
for execution limits, [disaster-capabilities.md](disaster-capabilities.md) for coverage,
and [capability-status.md](capability-status.md) for release evidence.

## Flow

1. Normalize one hazard, explicit geographic scope (country or worldwide), information
   need, output mode, and optional event discriminators.
2. Select registry-approved providers. Unsupported combinations return
   `current_disaster_coverage_unavailable` without a factual model response.
3. Discover and select a physical event using deterministic, hazard- and country-safe
   policy. Ambiguous events remain separate and are disclosed.
4. Retrieve eligible situation evidence and preserve provider failures independently.
5. Reconcile observations into canonical temporal evidence. Revisions, conflicts,
   omissions, freshness, and provenance remain explicit; missing is not zero.
6. Render a deterministic report with source metadata, sections, gaps, warnings, and
   retrieval time.

Default tool sequence:

```text
list_sources_for_task
find_disaster_event
retrieve_situation_evidence
reconcile_disaster_evidence
compose_disaster_answer
```

The parser routes recognized current-event questions, including “news” requests, to
this path. Explicit worldwide requests use the same normalized-task and capability
selection path as named-country requests, without inventing a country. Worldwide
ranking and wording are supplied by the selected hazard policy; the result is limited
to event discovery, not global impact coverage.

## Evidence and authority

Official and scientific sources outrank supplementary reports. Every fact retains its
source, stable ID, canonical URL, event ID when available, and source/retrieval times.
Same-source corrections supersede the current projection but do not erase history.
Cross-source disagreement remains a conflict. Provider text is bounded and sanitized;
the renderer does not infer damage from magnitude, intensity, or bulletin absence.

Hypotheses, triage, decision support, specialist coordination, multimodal observations,
and contextual media are typed artifacts. They cannot create verified facts, expand
source authority, issue public warnings, or select events.

## Providers

- JMA rolling and significant-earthquake feeds discover Japan events.
- USGS provides bounded named-country and worldwide earthquake discovery.
- FDMA provides official Japan earthquake situation reports.
- JMA provides tsunami status for selected events with a JMA identifier.
- ReliefWeb provides configured preliminary supplementary reports.
- NCHMF, FIRMS, GFM, and explicitly registered CAP paths cover Roadmap-2 roles.

See [docs/sources](sources/) for source-specific limits and tests. Event-associated
photos are a separate presentation feature documented in [event-media.md](event-media.md).

## Configuration and checks

Adapters use `apps/api/.env` or the process environment:

```text
DISASTER_PROVIDER_TIMEOUT_SECONDS=10
DISASTER_PROVIDER_MAX_RESPONSE_BYTES=1000000
RELIEFWEB_APP_NAME=(optional approved name)
```

Default tests use deterministic fixtures and do not require network access, Ollama, or
cloud credentials. The optional live smoke test is:

```powershell
uv run --project apps/api python scripts/live_disaster_smoke.py
```
