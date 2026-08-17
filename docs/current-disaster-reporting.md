# Current-disaster reporting

The agent-first assistant has a deterministic current-disaster path for recognized
hazard and country requests. Current-event wording includes requests for “news,” so
questions such as “Any news about earthquakes in Thailand?” cannot fall through to the
general-purpose model. A `DisasterQueryParser` resolves exact hazard aliases and the
active versioned country catalog before source-backed tool execution. Short ISO codes
must be written in uppercase; this prevents ordinary words such as “can,” “are,” or
“in” from being mistaken for countries after a global catalog is activated. The packaged
three-country catalog is a fail-closed fallback; validated global updates are promoted
autonomously as described in
[Autonomous country catalog updates](country-catalog-automation.md):

An explicit worldwide earthquake request follows a separate deterministic branch:

> Any earthquake news worldwide?

That branch queries the same registry-approved USGS adapter without country bounds,
within a 30-day window, with a minimum magnitude of 4.5 and a maximum of 50 records.
It selects the latest event by event time, or the strongest by magnitude when the
request says "strongest," "largest," or equivalent wording. It does not assign a fake
country to offshore events and it does not invoke the general-purpose model. The
result is deliberately partial because globally complete impact, warning, and response
evidence is not connected.

See [Capability and promotion status](capability-status.md) for the authoritative
distinction between this implemented path, passing automated gates, and normative
promotion evidence.

> There was a recent earthquake in Japan. Please update me with the latest information about the damages in Japan.

The flow is:

1. Normalize the question and extract one typed hazard, one canonical country,
   time intent, focus, and
   optional dates, coordinates, magnitude, prefecture, city, or event identifier.
2. Pass that same normalized query to the source-backed workflow. A provider
   registry selects event sources by role, hazard, country scope, and configuration.
   If no event source supports the combination, return
   `current_disaster_coverage_unavailable` without invoking the model. Explicit dates
   use the configured country calendar boundary; Japan August 5 spans
   `2026-08-04T15:00:00Z` through `2026-08-05T15:00:00Z`.
3. Query the bounded event-source ports for candidate observations and construct an
   auditable physical-event partition. The partition preserves each observation and
   its assignment rationale. Equivalence components must be pairwise complete, so a
   transitive A-B-C chain cannot merge unrelated A and C events. Ambiguous assignments
   remain separate and provider ordering does not change the result.
4. Rank physical-event candidates by maximum JMA intensity, magnitude, provider significance,
   recency, and an aftershock penalty. Magnitude and intensity materially outweigh
   a small age difference, so a destructive mainshock remains preferred to a later
   routine tremor. Explicit date, location, coordinate, magnitude, and event-ID
   discriminators override generic ranking. A
   materially ambiguous pair of unrelated events is disclosed instead of being
   silently conflated.
5. Retrieve situation records for the selected event from the bounded situation
   sources.
6. Build canonical temporal evidence state. Every accepted observation retains its
   `ReportedFact`, `SituationReport`, `SourceReference`, observation/publication/update/
   retrieval times, and typed lifecycle state. Same-source corrections supersede but
   never delete history; cross-source disagreements remain conflicts; explicit unknown
   stays missing; explicit zero remains an observed zero. A later report that omits a
   prior claim records that omission without silently retracting the prior value.
7. Project the canonical state into the backward-compatible `EvidencePacket`, then
   render a deterministic source-backed report with structured sections, source
   metadata, warnings, and retrieval time.
8. Derive a bounded internal hypothesis artifact from canonical state. It remains
   machine-typed as inferred and is not included in verified current-fact rendering.
9. Derive an internal incident-priority assessment from the same canonical state.
   Verified severity and impact signals retain evidence lineage. Missing, stale,
   conflicting, or ambiguous evidence can raise review priority but cannot silently
   reduce it. Apply the closed triage authority policy: only eligible low/moderate
   assessments may receive reversible internal monitor/queue actions; high,
   uncertainty-marked, and critical assessments require human review or escalation.
   The assessment and decision do not create facts or external operational authority.
10. For an explicit decision-support information need, derive a deterministic advisory
    artifact from that same EW, priority, and triage lineage. Confirmed facts,
    preliminary observations, source estimates, disputed observations, Disaster
    Monitor's inferred estimates, assumptions, contradictions, evidence gaps, and
    analytical options remain machine-distinct.
    Every option identifies its support, trade-offs, uncertainty, human-approval state,
    and prohibited public-warning, evacuation, and resource-order actions. Fabricated
    current facts or omitted material contradictions reject the artifact and leave the
    deterministic evidence report in place. Paired counterfactual scenarios reuse the
    calibrated human-impact hypothesis, expose assumption sensitivity and evidence
    gaps, and retain the same closed policy constraints. A bounded internal monitoring
    recommendation is available only when its leading premise has current confirmed
    fact lineage and triage does not require human intervention; preliminary,
    source-estimated, disputed, stale, or unresolved premises disable that layer. The
    bounded autonomy controller may apply only that selected option when it
    is a reversible low/moderate-consequence internal state change. The request-scoped
    final state and termination reason are inspectable. A prohibited public warning,
    evacuation directive, resource order, unselected option, or authority mismatch
    leaves state unchanged and immediately downgrades the result to advisory-only.
11. Issue request-scoped typed handoffs from the supervisor to the evidence specialist
    and, when decision support exists, the decision specialist. The broker derives task
    ownership and granted permissions from a closed role policy; each artifact carries
    state, evidence, and source provenance. Malformed, ambiguous, or privilege-expanding
    handoffs are rejected and the existing single-supervisor path remains active. When at least two
    eligible specialists have artifacts, they emit typed provenance-bound findings and
    a bounded coordinator merges only identical conclusions for the same finding key.
    Unknown evidence, a changed safety fingerprint, a specialist disagreement, or more
    than two iterations discards collaborative output and retains the single-supervisor
    result. A budgeted coordination supervisor compares the merged finding keys with a
    deterministic sufficiency checklist derived from the EW, decision, conflict, and
    multimodal artifacts present. It terminates only on a complete bounded end state;
    outages, missing findings, policy/provenance violations, deadlocks, and handoff/
    finding/iteration overruns preserve the already-completed default plan. This
    request-scoped handoff cannot grant background or inherited authority; the separate
    Roadmap-2 scheduler only runs allowlisted evidence investigations. The API
    exposes status, artifact identity, provenance, checklist, bounded rationale, and
    termination reason without specialist scratch work or chain-of-thought. The first
    highlighted analytical follow-up uses the governed
    `analytical-tuning:v3-governed` parameter set under release
    `analytical-tuning-release:v3-governed`. Continuous signals are normalized counts
    from decision gaps, conflicting claim families, and multimodal review units—not
    presence booleans. The checksum-bound automated release changes three
    production-derived attenuated regimes and preserves repeated-run, repository
    regression/shift, grounding, critical-safety, sufficiency, and termination
    guardrails.
    The weights affect display priority only; they cannot change the checklist, facts,
    source authority, permissions, safety thresholds, termination, or actions.
12. When the request contains admitted image bytes, associate each asset to the selected
    physical event using explicit hazard, country, capture-time, capture-role, event-ID,
    and WGS84 footprint metadata. Only uniquely associated assets enter bounded local
    visual analysis. Store results as analytical observations linked to the EW version,
    then build a typed analytical COP when pixel-supported damage and geometry exist.
13. After event selection, independently ask the optional event-media service for three
    contextual source photos. Candidate pages and image hosts must match the maintained
    event-media registry. Application policy checks publication/capture windows, hazard,
    selected-event geography, explicit years, event identifiers, media dimensions, and
    duplicate checksums. Rejected candidates are never displayed. Accepted items retain
    caption, publication/capture date, credit, source, rights status, association status,
    and selected-event lineage. This optional presentation step cannot add facts, alter
    event selection, or prevent the text report from completing.

The current report path does not use model memory for current facts. This keeps
the report useful when Ollama is unavailable and prevents generated prose from
introducing unsupported live claims. Ordinary assistant and map questions still
use the existing local Qwen path.

Every request enters the disaster-agent use case before delegation. The deterministic
safety gate and validator finish factual routing before any optional structured-model
planning or review. If agent inference is unavailable or invalid, the five-step default
tool plan runs without Ollama. The legacy report service is a compatibility facade over
those same tools. Responses may add safe actions,
source IDs, evidence count, gaps, and termination status; they never expose hidden
reasoning, prompts, raw model/provider output, secrets, or stack traces.
Hazards, countries, requested information needs, and output modalities must be present
in the normalized user text; structured model output cannot add them. Questions about
the map that contain no recognized disaster hazard remain on the ordinary map-assistant
path. A plan also cannot invoke multimodal tools unless an asset crossed the explicit
admission boundary.
The same metadata includes priority, score, internal triage action, autonomy mode, and
whether human intervention is required. These are policy outcomes, not model reasoning.
The machine-readable decision-support response and browser presentation preserve source
epistemic type separately from Disaster Monitor's inferred estimate. Coordination
metadata includes both the analytical parameter-set ID and approved release ID.

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
  independent global earthquake event source. Requests use the normalized country's
  geographic bounds, and returned coordinates are checked against packaged simplified
  country polygons before the canonical query country is assigned. A malformed feature
  becomes a record issue while valid sibling features remain. Generic searches use a bounded,
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

The rolling JMA and durable JMA registrations advertise earthquake event discovery
for `JPN`; USGS advertises global earthquake event discovery. FDMA advertises Japan
earthquake situation evidence. JMA tsunami evidence additionally requires a selected
event carrying a JMA identifier. ReliefWeb advertises configured global supplementary
situation evidence for recognized hazards. Disabled ReliefWeb is retained as a typed
configuration limitation rather than being misreported as a network failure. Each
selected source can fail independently; partial results expose a safe warning rather
than hiding the failure. Provider diagnostics
retain a stable reason code, retryability, and safe HTTP status for live diagnostics.
Each registration also owns its allowed HTTPS hosts. The shared transport rejects a
target before making a request when it is outside that set, and the composite rejects
normalized records whose stable source ID or canonical source URL does not match the
registration. Startup validation keeps the packaged catalog, registration, and adapter
source policies aligned.
NCHMF adds Vietnam national warning headlines for flood, landslide/flash-flood, and
tropical cyclone. Configured FIRMS adds satellite active-fire observations and
configured GFM adds analytical flood-product availability; neither is an official
incident declaration. A generic CAP adapter is available only through explicit
authority registration. Weather, automatic satellite imagery retrieval, geocoding,
broad news evidence aggregation, authentication, and official warning map overlays
remain unsupported. The bounded event-photo presentation path is documented in
[Event-associated source media](event-media.md); its pages and images are contextual
media, not provider evidence.

Physical-event clustering is application policy rather than transport composition.
The earthquake policy can merge matching JMA and USGS observations while preserving
both identifiers. It refuses to merge across hazards or countries and keeps nearby
independent events separate. Hazards without a dedicated policy use a conservative
newest-event policy with ambiguity disclosure.

## Evidence and freshness rules

Evidence precedence uses adapter-assigned `SourceAuthority`: national authority,
scientific authority, humanitarian aggregator, then secondary. Within that ordering,
effective source time and typed fact status break ties, followed by a stable key.
Effective claim chronology uses update time, publication time, observation time, then
retrieval time. Publisher-name substring
matching is not used. Every normalized fact retains its source, canonical URL, event
identifier, stable source ID, and the available event, publication, update, and retrieval
timestamps.
Official JMA/FDMA and scientific USGS records have higher priority than supplementary
reports, and newer same-source official figures become current while older revisions
remain in history. Different cross-source values are retained as typed conflicts and a
compatibility warning rather than silently discarded.

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
  ReliefWeb application name. Placeholder or missing names keep the registration
  disabled and visible as a configuration limitation.

ReliefWeb requests use the normalized country name, a typed hazard-to-ReliefWeb mapping,
and the normalized date range. They do not use the selected event's location or provider
identifiers as mandatory free-text terms: ReliefWeb's ``AND`` query parser would make
valid country/hazard reports disappear when a report uses a different place description.
Event-specific correlation remains application-owned after retrieval. Nested filter
conditions are built in one tested request builder. ReliefWeb remains supplementary and
its extracted figures are not promoted to official national totals.

The default unit, adapter, HTTP, and system tests use deterministic fixtures and
do not require network access, Ollama, or cloud credentials. The Playwright
system test starts fake JMA and ReliefWeb providers and submits the exact target
request.

## Source Intelligence evaluation

The executable SI gates run with:

```powershell
uv run --directory apps/api pytest -q tests/evaluation
```

The suite uses the frozen files under
`apps/api/tests/evaluation/fixtures/source_intelligence/`. It covers the packaged
coverage matrix, event-conditioned selection, source-policy mutations, provider fault
episodes, revision and missing-value outcomes, and adversarial source-candidate cases.
It is collected by the normal backend test command and therefore runs in CI.

These SI-A–SI-C tests are the normative promotion protocol for the bounded approved-
source runtime and currently pass. They do not approve candidate sources; candidate
trust promotion remains human-only. See
[Capability and promotion status](capability-status.md).

Candidate assessment consumes structured metadata only. `SourceScout` infers supported
roles, screens unsafe or misleading identities, and writes records to a candidate-only
store. Those records cannot enter the trusted catalog or disaster evidence types, and a
positive assessment remains pending human approval. Online crawling and automatic
catalog promotion are not connected.

## Evidence / World-State evaluation

The executable EW-A, EW-B, and EW-C gates run with:

```powershell
uv run --directory apps/api pytest -q tests/evaluation/test_evidence_world_state.py
```

Frozen fixtures are separate from Source Intelligence under
`apps/api/tests/evaluation/fixtures/evidence_world_state/`. They cover physical-event
identity, temporal revisions/conflicts/missingness/freshness, and labeled hypothesis
outcomes. The evaluator calculates assignment and ambiguity rates, prohibited
conflations, per-class temporal metrics, ECE, and Brier score against a fixed 0.5 naive
baseline. Fault-injection regressions prove detection of cross-event merging,
destructive history replacement, missing-as-zero conversion, miscalibration, and
hypothesis promotion into observed products.

This is automated/synthetic gate evidence. Normative EW promotion remains pending
locked external historical provenance and independently adjudicated hidden outcomes;
see [Capability and promotion status](capability-status.md).

Multimodal analytical state is a separate versioned extension whose observations
cannot overwrite those claim histories. See
[Multimodal situational awareness](multimodal-awareness.md) for the exact input,
association, model, COP, evaluation, and pending-gate boundaries.

The initial hypothesis rule is deliberately narrow and deterministic. It evaluates a
material-human-impact proposition from fresh numeric fatality, injury, and missing-
person observations. It does not retrieve data, forecast future impacts, use Ollama,
or enter verified-fact rendering. For an explicit decision-support request, it is
projected as a typed inferred estimate with public rationale rules. EW state is
request-scoped; persistence, continuous monitoring, and learned causal reasoning remain
future work. Bounded request-scoped multimodal state is implemented separately.

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
unknown fields to zero. Raw report content remains in its immutable snapshot; the
rendered qualitative section uses a short source notice instead of exposing a large
PDF text extraction. Counts expressed as rescue incidents remain operational-response
facts and are not relabeled as rescued people.
