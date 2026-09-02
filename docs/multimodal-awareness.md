# Multimodal situational awareness

Disaster Monitor has a bounded, local-first multimodal path for operator-supplied PNG
or JPEG images. It does not retrieve analytical imagery.

An API caller can attach at most three images to `POST /api/v1/assistant`.
Each image can be no larger than 5 MB.

Each image requires explicit source attribution, capture time, WGS84 footprint,
disaster, country, and capture role. The API accepts base64 image bytes only.
It does not accept URLs or filesystem paths.

The separate [event-associated source-media](event-media.md) path retrieves bounded
publisher previews after physical-event selection.

Those previews are not admitted multimodal assets. They are not sent to the visual
analyzer and cannot produce visual observations or map geometry.

They cannot enter canonical evidence state.

This capability extends the selected `PhysicalEventIdentity` and canonical
`EvidenceWorldState`. It does not create a separate event or truth system.

## Evidence and authority model

Raw `MultimodalAsset` values retain a content checksum, source attribution, capture
metadata, georeference, processing level, and parent lineage.

Missing capture time or georeference creates an orphan. Malformed geometry, naive
timestamps, invalid country codes, and unsupported media are rejected.

Orphaned, ambiguous, and unmatched assets cannot reach visual analysis.

`MultimodalEventAssociator` uses trusted metadata only. It compares typed disaster and
country, supplied event identifiers, capture-role time windows, and a validated WGS84
footprint against the selected physical event.

Image pixels and model output do not influence event association. A near-boundary
result remains ambiguous instead of being forced into the selected event.

Visual results are separate `VisualObservation` analytical artifacts. They are never
`ReportedFact` values and cannot overwrite textual claim history.

Each result retains the asset, association, physical event, model digest, adapter
version, analysis version, prompt version, preprocessing version, temperature, and
seed.

Block questions that ask an image to establish casualties, personal identity, official
warnings or orders, government decisions, or authoritative totals.

Discard unsafe numeric casualty output. Model confidence does not confer source
authority.

The default adapter is the local Ollama model `qwen3-vl:2b`. No inference occurs on
text-only requests.

Ordinary tests use a fake visual port and do not require Ollama. The default output
cap is 384 tokens, temperature is zero, and seed is 7.

Each observation records these values.

Install the real model separately:

```powershell
ollama pull qwen3-vl:2b
ollama list
```

The local model implements the application `VisualAnalyzer` port. No hosted or paid
vision service is configured.

## Common operational picture

`CommonOperationalPicture` is a renderer-independent application artifact tied to a
multimodal-state version.

Source geometry and analytical geometry use separate types:

- `SourceMapFeature` requires a source ID, source assets, attribution, uncertainty,
  and official or source-supplied authority.
- `AnalyticalMapFeature` requires source assets and visual observations. It has
  immutable `analytical_generated` authority.

The current production path creates analytical damage-footprint overlays only. It
does not ingest or publish an official warning boundary.

The browser validates physical-event and state lineage, provenance, authority, status,
uncertainty, and WGS84 geometry before rendering.

`OpenLayersMapAdapter` exposes one focused COP operation.

Its legend uses text labels, color, and solid, dotted, and dashed patterns.
Source or official layers remain distinguishable from analytical layers.

The bounded agent tools are `analyze_multimodal_assets` and
`build_common_operational_picture`.

They consume only already-admitted workspace artifacts. The model cannot choose an
image URL, path, provider, model, geometry, or authority.

If image metadata or inference fails, keep the source-backed text path available and
record the gap in the investigation.

## Evaluation layers and current status

This section records passing automated harnesses and pending normative evidence.
The cross-family vocabulary is defined in
[Capability and promotion status](capability-status.md).

Run the fast deterministic MM safety gate with normal backend tests:

```powershell
uv run --directory apps/api pytest -q tests/evaluation/test_multimodal.py tests/evaluation/test_operator_study.py
```

The gate covers metric integrity, majority-class faults, prohibited visual claims,
association adversaries, geometry, EW lineage, provenance, authority, browser
validation, and operator-harness integrity.

It is not a substitute for the real benchmark or a human study.

The full gate requires licensed, held-out slices from xBD, FloodNet, DisasterInsight,
and DM-specific operator-curated cases.

Store them under the ignored `data/` directory. Copy and complete the selection
template outside Git. Lock exact sample IDs and checksums.

```powershell
uv run --directory apps/api python scripts/prepare_multimodal_benchmarks.py `
  --staged-root ../../data/multimodal `
  --selection-file ../../data/multimodal/selection.json
```

Preparation fails unless all named families, four damage classes, answerable,
unanswerable and prohibited VQA cases, and associated, ambiguous, unmatched and
orphaned cases are present.

Run model inference and calculate metrics from prediction and label pairs:

```powershell
uv run --directory apps/api python scripts/run_multimodal_release.py `
  --staged-root ../../data/multimodal `
  --model qwen3-vl:2b `
  --output ../../data/multimodal/release-result.json
```

The command reports machine-readable and concise human results. It returns non-zero
if the manifest, asset checksums, model, capability metrics, or safety metrics fail.

It requires damage macro-F1 of at least 0.85 and absolute macro-F1 improvement of at
least 0.05 over the frozen constant-no-visible-damage baseline.
It requires VQA factual accuracy of at least 0.90.
It requires event and geotemporal association of at least 0.99.
It requires layer attribution of at least 0.99.
It requires complete provenance plus displayed status and uncertainty.

Safety violations are non-compensatory.

The repository does not contain licensed benchmark files or a completed locked
selection.

xBD requires its dataset access process. FloodNet must come from its official
challenge release. An authoritative public DisasterInsight data release and license
have not been identified.

The full MM-A/MM-B performance gate is pending. Adapter implementation and automated
transport and safety tests do not replace licensed benchmark inference results.

MM-C also requires legitimate expert or operator results.

The frozen protocol is `operator_study_protocol.v1.json`.

It requires at least six study-local participant codes, paired text-only and COP
conditions, balanced A/B ordering, approved expertise categories, and the predefined
task-completed-without-critical-error outcome.

It rejects PII, simulated users, LLM judges, missing pairs, and unbalanced ordering.

Store results only under ignored `data/operator-study/`. Then run:

```powershell
uv run --directory apps/api python scripts/run_mm_operator_study.py `
  --results ../../data/operator-study/results.json `
  --output ../../data/operator-study/score.json
```

The human-performance gate remains pending because no legitimate participant records
exist. Automated harness tests cannot satisfy it.

## Intentionally unsupported

There is no automatic analytical or satellite-image retrieval, continuous
satellite/aerial monitoring, live raster service, official-warning overlay provider,
arbitrary map publication, or OCR pipeline.
There is no persistent multimodal database, background worker, hosted vision model,
or operational instruction generation.

The source-media gallery is a bounded contextual presentation feature, not this
analytical pipeline.

Triage and advisory decision support operate over canonical evidence. Visual
observations remain analytical inputs and cannot become source facts or authorize
consequential action.
