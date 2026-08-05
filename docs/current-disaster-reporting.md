# Current-disaster reporting

The assistant has a deterministic current-disaster path for supported earthquake
requests. The exact request below is classified before the language model is
consulted:

> There was a recent earthquake in Japan. Please update me with the latest information about the damages in Japan.

The flow is:

1. Normalize the question and extract hazard, geography, time intent, focus, and
   optional dates, coordinates, magnitude, prefecture, city, or event identifier.
2. Query the bounded event-source ports for recent Japanese earthquake candidates.
3. Rank candidates by recency and significance, with an aftershock penalty. A
   materially ambiguous pair of unrelated events is disclosed instead of being
   silently conflated.
4. Retrieve situation records for the selected event from the bounded situation
   sources.
5. Reconcile typed facts by source priority and effective update time. Missing
   values remain missing; a missing damage figure is not rendered as zero.
6. Render a deterministic source-backed report with structured sections, source
   metadata, warnings, and retrieval time.

The current report path does not use model memory for current facts. This keeps
the report useful when Ollama is unavailable and prevents generated prose from
introducing unsupported live claims. Ordinary assistant and map questions still
use the existing local Qwen path.

## Implemented providers

The initial provider set is deliberately narrow:

- `JmaEarthquakeAdapter` reads the Japan Meteorological Agency's machine-readable
  earthquake JSON list and translates event time, location, magnitude, depth, and
  maximum intensity when present.
- `UsgsEarthquakeAdapter` queries the documented USGS FDSN GeoJSON catalog as an
  independent earthquake event source.
- `JmaTsunamiSituationAdapter` reads JMA tsunami JSON status messages related to
  the selected JMA event.
- `ReliefWebSituationAdapter` reads supplementary ReliefWeb JSON reports and
  extracts only bounded, clearly preliminary narrative facts. ReliefWeb values
  are not treated as official totals.

The JMA and USGS event adapters are composed together. The JMA and ReliefWeb
situation adapters are composed together. Each source can fail independently;
partial results expose a warning rather than hiding the failure. No weather,
flood, satellite, geocoding, news, authentication, or map-overlay provider is
implemented by this feature.

## Evidence and freshness rules

Every normalized fact retains its source, canonical URL, event identifier, and
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
- `RELIEFWEB_APP_NAME` (default `disaster-monitor-local`)

The default unit, adapter, HTTP, and system tests use deterministic fixtures and
do not require network access, Ollama, or cloud credentials. The Playwright
system test starts fake JMA and ReliefWeb providers and submits the exact target
request.

## Optional live-provider smoke test

The opt-in structural smoke test is excluded from normal CI:

```powershell
uv run --project apps/api python scripts/live_disaster_smoke.py
```

It checks that a candidate event, event/source timestamps, canonical URLs, and a
source-backed report are returned. It does not assert changing casualty or damage
figures. This smoke test was not run as part of the implementation verification.

Rapidly changing disaster figures remain provisional. A source can revise an
event, publish a correction, or report only a local impact. The report therefore
keeps source attribution and uncertainty visible and does not generalize local
evidence to all of Japan.

