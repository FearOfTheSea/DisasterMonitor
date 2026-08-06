# Current-disaster reporting

The assistant has a deterministic current-disaster path for recognized hazard and
country requests. A `DisasterQueryParser` resolves exact hazard aliases and a
packaged country catalog before the language model is consulted:

> There was a recent earthquake in Japan. Please update me with the latest information about the damages in Japan.

The flow is:

1. Normalize the question and extract one typed hazard, one canonical country,
   time intent, focus, and
   optional dates, coordinates, magnitude, prefecture, city, or event identifier.
2. Pass that same normalized query to the source-backed workflow. Explicit dates
   use the configured country calendar boundary; Japan August 5 spans
   `2026-08-04T15:00:00Z` through `2026-08-05T15:00:00Z`.
3. Query the bounded event-source ports for candidate events.
4. Rank candidates by maximum JMA intensity, magnitude, provider significance,
   recency, and an aftershock penalty. Magnitude and intensity materially outweigh
   a small age difference, so a destructive mainshock remains preferred to a later
   routine tremor. Explicit date, location, coordinate, magnitude, and event-ID
   discriminators override generic ranking. A
   materially ambiguous pair of unrelated events is disclosed instead of being
   silently conflated.
5. Retrieve situation records for the selected event from the bounded situation
   sources.
6. Reconcile typed facts by source priority and effective update time. Missing
   values remain missing; a missing damage figure is not rendered as zero.
7. Render a deterministic source-backed report with structured sections, source
   metadata, warnings, and retrieval time.

The current report path does not use model memory for current facts. This keeps
the report useful when Ollama is unavailable and prevents generated prose from
introducing unsupported live claims. Ordinary assistant and map questions still
use the existing local Qwen path.

## Implemented providers

The initial provider set is deliberately narrow:

- `JmaEarthquakeAdapter` reads the Japan Meteorological Agency's machine-readable
  earthquake JSON list and translates event time, location, magnitude, depth, and
  maximum intensity when present. It remains a recent-bulletin source and is
  bounded to its first 200 entries.
- `JmaSignificantEarthquakeAdapter` reads the official JMA emergency-earthquake-
  warning history, which retains warning-level events beyond the rolling bulletin
  list. It is a durable discovery source, not a visual-map scrape.
- `UsgsEarthquakeAdapter` queries the documented USGS FDSN GeoJSON catalog as an
  independent earthquake event source. Generic searches use a bounded,
  magnitude-ordered query with a moderate minimum magnitude and do not request
  unused expanded origins or magnitude collections.
- `FdmaSituationReportAdapter` matches the newest official Fire and Disaster
  Management Agency earthquake report by event date and geographic identity,
  extracts text from HTML or text-based PDFs, and attributes normalized human,
  damage, infrastructure, and response facts to that report.
- `JmaTsunamiSituationAdapter` reads JMA tsunami JSON status messages related to
  the selected JMA event.
- `ReliefWebSituationAdapter` reads supplementary ReliefWeb JSON reports and
  extracts only bounded, clearly preliminary narrative facts. ReliefWeb values
  are not treated as official totals.

The rolling JMA, durable JMA, and USGS event adapters are composed together. FDMA
is the primary human-impact source, with JMA tsunami and optionally configured
ReliefWeb as supplementary sources. Each source can fail independently; partial
results expose a safe warning rather than hiding the failure. Provider diagnostics
retain a stable reason code, retryability, and safe HTTP status for live diagnostics.
No weather,
flood, satellite, geocoding, news, authentication, or map-overlay provider is
implemented by this feature.

## Evidence and freshness rules

Human-impact precedence is newest matching FDMA report, then another newer
event-specific Japanese government source, then an event-specific ReliefWeb report,
then other explicitly configured supplementary sources. Every normalized fact retains its source, canonical URL, event identifier, and
the available event, publication, update, and retrieval timestamps. Official JMA
and USGS facts have higher priority than supplementary reports, and newer
official figures replace older official figures for the same claim. Different
values are retained as a conflict warning rather than silently discarded.

Provider text is bounded, stripped of markup, and filtered for instruction-like
content before it can enter the evidence packet. The renderer never infers
damage from magnitude, intensity, or tsunami advisories. It distinguishes “no
damage reported in this source” from “no reliable damage information found.”

The report's freshness time is the retrieval time, not the source publication
time. A source update older than 24 hours produces a stale-data warning. There is
no persistent cache or background processing.

## Configuration and offline behavior

The live adapters use these settings in `apps/api/.env` or the process
environment:

- `DISASTER_PROVIDER_TIMEOUT_SECONDS` (default `10`)
- `DISASTER_PROVIDER_MAX_RESPONSE_BYTES` (default `1000000`)
- `RELIEFWEB_APP_NAME` (unset by default). If set, it must be a pre-approved
  ReliefWeb application name; placeholder names do not compose the adapter.

The default unit, adapter, HTTP, and system tests use deterministic fixtures and
do not require network access, Ollama, or cloud credentials. The Playwright
system test starts fake JMA and ReliefWeb providers and submits the exact target
request.

## Optional live-provider smoke test

The opt-in structural smoke test is excluded from normal CI:

```powershell
uv run --project apps/api python scripts/live_disaster_smoke.py
```

It runs both the generic Japan request and an event-specific Kumamoto diagnostic
request. For every composed provider it prints success, no-records, skipped, or
failure status, typed failure code, safe HTTP status, record counts, selected event
and provider IDs, and latest source timestamps. It does not assert changing live
casualty or damage figures.

Rapidly changing disaster figures remain provisional. A source can revise an
event, publish a correction, or report only a local impact. The report therefore
keeps source attribution and uncertainty visible and does not generalize local
evidence to all of Japan.

FDMA extraction is intentionally text-only. It supports HTML and extractable
text-based PDFs, preserves Japanese labels in fact provenance, and returns a
typed partial-provider issue when a PDF requires OCR, has an image-only table,
or changes structure. It does not infer values from images or silently convert
unknown fields to zero.
