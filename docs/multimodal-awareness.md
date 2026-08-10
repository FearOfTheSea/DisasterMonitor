# Multimodal situational awareness

Disaster Monitor has a bounded, local-first multimodal path for operator-supplied PNG
or JPEG images. It does not retrieve imagery. An API caller may attach at most three
images, each no larger than 5 MB, to `POST /api/v1/assistant` as base64 plus explicit
source attribution, capture time, WGS84 footprint, hazard, country, and capture role.
URLs and filesystem paths are not accepted as image inputs.

This capability extends the selected `PhysicalEventIdentity` and canonical
`EvidenceWorldState`; it does not establish a separate event or truth system.

## Evidence and authority model

Raw `MultimodalAsset` values retain a content checksum, source attribution, capture
metadata, georeference, processing level, and parent lineage. Missing capture time or
georeference creates an orphan. Malformed geometry, naive timestamps, invalid country
codes, and unsupported media are rejected. Orphaned, ambiguous, and unmatched assets
cannot be sent to visual analysis.

`MultimodalEventAssociator` uses only trusted metadata. It compares typed hazard and
country, event identifiers when supplied, capture-role time windows, and a validated
WGS84 footprint against the selected physical event. Image pixels and model output do
not influence event association. A near-boundary result remains ambiguous rather than
being forced into the only selected event.

Visual results are separate `VisualObservation` analytical artifacts. They are never
`ReportedFact` values and cannot overwrite textual claim history. Every result retains
the asset, association, physical event, model digest, adapter version, analysis version,
prompt version, preprocessing version, temperature, and seed. Questions asking the
image to establish casualties, personal identity, official warnings/orders, government
decisions, or authoritative totals are blocked; unsafe numeric casualty output is
discarded. Model confidence never confers source authority.

The default adapter is the local Ollama model `qwen3-vl:2b`. It is lazy in the sense
that no inference occurs on text-only requests. Ordinary tests use a fake visual port
and do not require Ollama. Its default output cap is 384 tokens, temperature is zero,
and seed is 7; each observation records these values. Install the real model separately:

```powershell
ollama pull qwen3-vl:2b
ollama list
```

The local model is a replaceable implementation of the application `VisualAnalyzer`
port. No hosted or paid vision service is configured.

## Common operational picture

`CommonOperationalPicture` is a renderer-independent application artifact tied to a
multimodal-state version. Source geometry and analytical geometry use separate types:

- `SourceMapFeature` requires a source ID, source assets, attribution, uncertainty,
  and either official or source-supplied authority.
- `AnalyticalMapFeature` requires source assets and visual observations and has an
  immutable `analytical_generated` authority.

The current production path creates analytical damage-footprint overlays only. It does
not ingest or publish an official warning boundary. The browser validates physical
event/state lineage, provenance, authority, status, uncertainty, and WGS84 geometry
before rendering. `OpenLayersMapAdapter` exposes one focused COP operation. Its legend
uses text labels and solid/dotted/dashed patterns as well as color so source/official
and analytical layers remain distinguishable.

The bounded agent tools are `analyze_multimodal_assets` and
`build_common_operational_picture`. They consume only already admitted workspace
artifacts. The model cannot choose an image URL, path, provider, model, geometry, or
authority. If image metadata or inference fails, the existing source-backed text path
remains available and the investigation records the gap.

## Evaluation layers and current status

The fast deterministic MM safety gate is collected by normal backend tests:

```powershell
uv run --directory apps/api pytest -q tests/evaluation/test_multimodal.py tests/evaluation/test_operator_study.py
```

It covers metric integrity, majority-class faults, prohibited visual claims,
association adversaries, geometry, EW lineage, provenance, authority, browser
validation, and operator-harness integrity. It is not a substitute for the real
benchmark or a human study.

The full gate requires licensed, held-out slices from xBD, FloodNet,
DisasterInsight, and DM-specific operator-curated cases. Store them under the ignored
`data/` directory. Copy and complete the selection template outside Git, then lock
exact sample IDs and checksums:

```powershell
uv run --directory apps/api python scripts/prepare_multimodal_benchmarks.py `
  --staged-root ../../data/multimodal `
  --selection-file ../../data/multimodal/selection.json
```

Preparation fails unless all named families, four damage classes, answerable,
unanswerable and prohibited VQA cases, and associated, ambiguous, unmatched and
orphaned cases are present. Run actual model inference and calculate metrics from the
prediction/label pairs with:

```powershell
uv run --directory apps/api python scripts/run_multimodal_release.py `
  --staged-root ../../data/multimodal `
  --model qwen3-vl:2b `
  --output ../../data/multimodal/release-result.json
```

The command reports machine-readable and concise human results and returns non-zero if
the manifest, asset checksums, model, capability metrics, or safety metrics fail. It
requires damage macro-F1 at least 0.85, absolute macro-F1 improvement of at least 0.05
over the frozen constant-no-visible-damage baseline, VQA factual accuracy at least
0.90, event and geotemporal association at least 0.99, layer attribution at least
0.99, and complete provenance plus displayed status/uncertainty. Safety violations are
non-compensatory.

The repository does not contain the licensed benchmark files or a completed locked
selection. xBD requires its dataset access process; FloodNet must come from its
official challenge release; an authoritative public DisasterInsight data release and
license have not been identified. The full MM-A/MM-B performance gate is therefore
pending, even though the real local adapter is installed and has passed an integration
smoke test.

MM-C additionally requires legitimate expert/operator results. The frozen protocol is
`operator_study_protocol.v1.json`: six or more study-local participant codes, paired
text-only and COP conditions, balanced A/B ordering, approved expertise categories,
and the predefined task-completed-without-critical-error outcome. It rejects PII,
simulated users, LLM judges, missing pairs, and unbalanced ordering. Store results only
under ignored `data/operator-study/`, then run:

```powershell
uv run --directory apps/api python scripts/run_mm_operator_study.py `
  --results ../../data/operator-study/results.json `
  --output ../../data/operator-study/score.json
```

The human-performance gate remains pending because no legitimate participant records
exist. Automated harness tests cannot satisfy it.

## Intentionally unsupported

There is no automatic image retrieval, continuous satellite/aerial monitoring, live
raster service, imagery provider, official-warning overlay provider, arbitrary map
publication, OCR pipeline, persistent multimodal database, background worker, hosted
vision model, decision support, triage, or operational instruction generation.
