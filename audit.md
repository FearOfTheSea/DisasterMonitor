# P0–P3 implementation audit

Audit date: 2026-09-22  
Requirements source: `/home/hieu/task.md`, tasks 1–110  
Audited revision: `5605994` plus the fixes listed below; no commit was created.

## Status rules

- **Complete**: the requested bounded production path exists, is wired into the
  application, and has deterministic coverage. External promotion may still be a
  separate deployment concern.
- **Partial**: useful code or a bounded slice exists, but a stated acceptance condition,
  runtime integration, durable history, UI/API path, or required evidence is missing.
- **Pending**: the requested outcome is not implemented or the requirement is primarily
  an evidence gate whose required evidence has not been collected.

Passing fixtures are not treated as external validation, and source/adaptor existence is
not treated as end-to-end product integration.

## Summary

| Priority | Complete | Partial | Pending | Total |
| --- | ---: | ---: | ---: | ---: |
| P0 | 13 | 8 | 1 | 22 |
| P1 | 8 | 24 | 1 | 33 |
| P2 | 20 | 15 | 0 | 35 |
| P3 | 15 | 5 | 0 | 20 |
| **Total** | **56** | **52** | **2** | **110** |

The strongest completed areas are product scope and provider rights, commercial-imagery
removal, operational projections and worker hardening, provider health, Ground job
durability, USGS event-product context, the provider-neutral CAP boundary and official
warning readers, authority-first warning presentation, and conservative exposure
wording. P2 adds a composed direct-COG fallback, offline snapshot behavior,
deterministic interoperability endpoints, bounded multi-country/multi-hazard
investigations, historical and meaningful-change views, an admitted controlled
publisher lane, and deterministic news clustering. P3's strongest area is the
end-to-end unverified field-report, privacy, review, import, non-evidence workspace,
and evidence-package boundary.

The largest gap is the difference between isolated capability code and a production
workflow. Exposure, hazard-context, spatial-watch, delivery, OpenAerialMap, comparison
manifest, and export modules generally have deterministic unit or adapter coverage but
are not composed into operator-facing use cases. The same pattern remains in several
P2 imagery analytics/offline-package helpers and P3 OSM/facility-context helpers.

## Issues fixed during this audit

1. Ground comparison manifests accepted arbitrary 64-character values as SHA-256
   checksums, naive timestamps, and duplicate/non-finite derived metrics. The comparison
   boundary now requires complete identities, aware timestamps, lowercase hexadecimal
   SHA-256 values, and finite uniquely named metrics.
2. Ground export bundles did not verify that packaged COGs matched the comparison
   manifest. An export now streams the files, requires both packaged COG checksums to
   match the before and after artifact checksums, and avoids loading large rasters into
   memory solely to hash or archive them.
3. Ground view claimed that a comparison manifest existed for its display-only pairing,
   although no production comparison-manifest path is wired. The UI now states the
   actual boundary explicitly.
4. Provider-rights annual review validation crashed on February 29 while constructing
   the prior-year boundary. It now uses a calendar-safe prior-year boundary, with a
   regression test.
5. GFM component lineage accepted arbitrary 64-character checksum text. It now
   requires a lowercase hexadecimal SHA-256 value.
6. OGC occurrence filters accepted timezone-naive datetimes and then failed with an
   internal aware/naive comparison error. The projection now rejects naive bounds at
   its application boundary.
7. Evidence-package verification checked ZIP paths, sizes, and hashes but accepted
   checksum-valid non-JSON or structurally invalid declared payloads. It now validates
   manifest identity and types, parses every declared JSON payload, enforces payload
   shapes and HTTPS source links, and checks incident identity consistency. The builder
   now prevents creating a package that its verifier would reject.
8. A multi-row field import validated privacy row-by-row while persisting, so an early
   row could remain stored when a later row was rejected for contact PII. All report
   text is now privacy-validated before the first row is persisted.
9. Capability documentation still claimed that no direct publisher was admitted even
   though the runtime registry and composition enable the rights-reviewed NASA Earth
   Observatory feed. The stale claims now match the bounded runtime state.

## P0 audit

| # | Status | Evidence | Remaining issue |
| ---: | --- | --- | --- |
| 1 | Complete | [ADR 0001](docs/adr/0001-evidence-native-local-first.md), [scope contract](docs/product-scope.v1.json) | None found. |
| 2 | Complete | [rights domain](apps/api/src/disaster_monitor/application/ports/provider_rights.py), [CI rights check](apps/api/scripts/check_provider_rights.py) | Human review must continue annually. |
| 3 | Complete | [public imagery providers](apps/api/src/disaster_monitor/infrastructure/satellite_imagery/providers.py), [commercial-removal integration tests](apps/api/tests/integration/test_satellite_imagery.py) | None found in the supported product path. |
| 4 | Complete | [Ground composition](apps/api/src/disaster_monitor/infrastructure/composition_builders.py), [local public-COG renderer](apps/api/src/disaster_monitor/infrastructure/ground_imagery/local_products.py), [rights documentation](docs/provider-rights.md) | CDSE availability and entitlement remain upstream/deployment dependencies, but a local public-product path exists. |
| 5 | Complete | [versioned rights manifest](apps/api/src/disaster_monitor/infrastructure/sources/resources/provider_rights.v1.json) | None found. |
| 6 | Complete | [rights contract tests](apps/api/tests/unit/test_provider_rights.py), [CI workflow](.github/workflows/ci.yml) | None found after the leap-day fix. |
| 7 | Partial | [reference corpus](evaluation/provider_reference_corpus.v1.json) covers all six hazards and records URLs, time bounds, expected observations, and gaps | There is only one historical case per hazard; the requested recent-and-historical coverage is absent. The common payload file contains normalized summaries, not the exact raw payload for each cited reference event. |
| 8 | Partial | [offline replay](apps/api/src/disaster_monitor/evaluation/provider_replay.py) checks fixture hashes and executes production adapters | Adapter fixtures are unrelated to the named external reference events, so this does not replay the exact payloads underlying those cases. |
| 9 | Partial | [replay metrics](apps/api/src/disaster_monitor/evaluation/provider_replay.py) publish per-hazard recall, merge/split, and latency values with thresholds | Each hazard has one expected observation. Recall is derived from hand-authored expected IDs, and merge/split rates are not measured over executable adversarial multi-record episodes. The results cannot support a broad monitoring claim. |
| 10 | Partial | [adversarial corpus](evaluation/adversarial_identity_cases.v1.json), [category lock test](apps/api/tests/evaluation/test_provider_replay.py) | Entries contain category/decision prose only; they have no event inputs and are never executed through identity policy. |
| 11 | Complete | [provider operational state](apps/api/src/disaster_monitor/domain/operations.py), [freshness policy](apps/api/src/disaster_monitor/application/ingestion/provider_freshness.py), PostgreSQL operational repositories | None found in the bounded telemetry contract. |
| 12 | Complete | [operations API](apps/api/src/disaster_monitor/presentation/http/system_routes.py), [operations UI](apps/web/src/features/operations/ui/OperationsPanel.tsx) | Deployment health still depends on workers actually running, which is correctly reported as misconfigured/unavailable. |
| 13 | Complete | [projection-owned incident service](apps/api/src/disaster_monitor/application/incidents/active_incidents.py), [production composition](apps/api/src/disaster_monitor/infrastructure/app_composition.py), [runbook](docs/operations/runbook.md) | The direct path remains limited to explicit no-database development mode. |
| 14 | Complete | [leased ingestion jobs](apps/api/src/disaster_monitor/infrastructure/operations/postgres_ingestion_jobs.py), [job tests](apps/api/tests/unit/test_leased_jobs_and_budgets.py) | None found. |
| 15 | Complete | [budget port](apps/api/src/disaster_monitor/application/ports/provider_budget.py), [PostgreSQL budget adapter](apps/api/src/disaster_monitor/infrastructure/operations/postgres_provider_budget.py) | Provider-specific real quotas must still be kept current operationally. |
| 16 | Partial | [backup/restore implementation](scripts/operational_backup.py), shell/PowerShell wrappers, [round-trip and rollback tests](apps/api/tests/unit/test_operational_backup.py) | No recorded disposable restore drill against the real PostgreSQL plus production artifact layout was found. Unit fault injection is not restore evidence. |
| 17 | Complete | [Ground job policy](apps/api/src/disaster_monitor/application/ground_imagery/jobs.py), [PostgreSQL leased queue](apps/api/src/disaster_monitor/infrastructure/ground_imagery/postgres_jobs.py), [artifact retention](apps/api/src/disaster_monitor/application/ground_imagery/artifact_access.py) | Deployment-specific capacity remains an operational concern. |
| 18 | Pending | [acceptance manifest](evaluation/ground_acceptance.v1.json), [fail-closed evaluator](apps/api/src/disaster_monitor/evaluation/ground_acceptance.py) | All four declared cases are `not_run`; `live_evidence` is empty. The target hardware gate passes, but no live sensor-path acceptance evidence, checksums, or operator-visible run results have been recorded. |
| 19 | Partial | [typed inspection timeline](apps/api/src/disaster_monitor/application/evidence/inspection.py) supports all requested event kinds | Runtime reports currently populate observations, situation reports, claim reconciliation, and coverage only. Warning lifecycle, Ground selection/acquisition, and watch-change records are not joined into a durable incident stream; [capability status](docs/capability-status.md) states this explicitly. |
| 20 | Partial | [claim inspection UI](apps/web/src/features/assistant/ui/AssistantEvidenceViews.tsx) shows why/source/status/times/authority and gaps | Coverage applies to canonical evidence-world claims. Material narrative sections and Event Brief measurements are not uniformly represented as inspectable claims. |
| 21 | Complete | [evidence reconciliation](apps/api/src/disaster_monitor/application/evidence/evidence_reconciliation.py), [inspection policy](apps/api/src/disaster_monitor/application/evidence/inspection.py), contradiction UI | Complete for canonical report claims; it does not imply every future product surface is covered. |
| 22 | Partial | [shared age badge](apps/web/src/shared/ui/DataAgeBadge.tsx) distinguishes source, projection, imagery, forecast, and retrieval semantics | Badges are not present across every layer: warning list validity, Event Brief source chronology, and several context surfaces still render plain timestamps or static text. |

## P1 audit

| # | Status | Evidence | Remaining issue |
| ---: | --- | --- | --- |
| 23 | Complete | [USGS product adapter](apps/api/src/disaster_monitor/infrastructure/earthquake/usgs_products.py), [HTTP route](apps/api/src/disaster_monitor/presentation/http/earthquake_context_routes.py), [integration tests](apps/api/tests/integration/test_usgs_earthquake_context.py) | Live upstream availability is not guaranteed. |
| 24 | Partial | [Event Brief ShakeMap controls and legend](apps/web/src/features/event-brief/ui/EventBrief.tsx) preserve MMI/PGA/PGV units | The primary map has no georeferenced ShakeMap layer in the [layer registry](apps/web/src/features/map/model/mapLayerRegistry.ts); the current UI shows source overlay/legend images only. |
| 25 | Partial | PAGER alert, exposure bins, probability bins, version, and interpretation exist in the USGS adapter/domain | Data is fetched on demand and not durably stored as event evidence; the UI shows only alert/version/bin count, not the probability distributions and uncertainty. |
| 26 | Partial | Ground-failure models, bounds, raster URLs/checksums, ShakeMap version, and interpretation are parsed | The operator UI exposes only product labels; no stored evidence or map/raster presentation is wired. |
| 27 | Complete | Event-scoped USGS OAF parsing and explicit non-global language are exposed in Event Brief | None found in the bounded USGS product scope. |
| 28 | Partial | [generic exposure service](apps/api/src/disaster_monitor/application/exposure/analysis.py) and typed domain outputs | The service is not composed into runtime dependencies or exposed through an event use case/API. |
| 29 | Partial | [WorldPop local raster adapter](apps/api/src/disaster_monitor/infrastructure/exposure/population_raster.py) | No configured dataset acquisition/cache, runtime composition, API, or Event Brief result path. |
| 30 | Partial | The same adapter provides a versioned GHSL fallback/cross-check | No production composition or disagreement presentation. |
| 31 | Partial | [local OSM exposure adapter](apps/api/src/disaster_monitor/infrastructure/exposure/local_osm.py) covers the requested facility classes | No Geofabrik extract lifecycle, runtime composition, API, or UI result path. |
| 32 | Complete | [exposure domain](apps/api/src/disaster_monitor/domain/exposure.py) and Event Brief wording consistently use intersection rather than affected-person claims | This policy is ready, but meaningful operator results depend on tasks 28–31. |
| 33 | Partial | [Event Brief](apps/web/src/features/event-brief/ui/EventBrief.tsx) contains all requested sections | Exposure, humanitarian/INFORM, gaps, and the cross-subsystem timeline are largely explanatory placeholders rather than event-associated data. |
| 34 | Partial | [local INFORM adapter](apps/api/src/disaster_monitor/infrastructure/hazard_context/inform.py) and baseline-vulnerability domain invariant | No runtime composition, API, or displayed values/vintage/aggregation level. |
| 35 | Complete | [generic CAP domain](apps/api/src/disaster_monitor/domain/warnings.py) models identity, lifecycle fields, info blocks, codes, areas, geocodes, polygons, circles, and references | None found in the bounded CAP model. |
| 36 | Complete | [NWS adapter](apps/api/src/disaster_monitor/infrastructure/weather/nws_alerts.py) projects NWS GeoJSON into the generic CAP domain | None found; current NWS behavior remains fixture-covered. |
| 37 | Complete | [MeteoAlarm Atom/CAP adapter](apps/api/src/disaster_monitor/infrastructure/weather/meteoalarm.py), [source documentation](docs/sources/meteoalarm-warnings.md) | Operator configuration is intentionally required; issuer-specific reuse terms still need ongoing review. |
| 38 | Complete | [NOAA CAP-TSU adapter](apps/api/src/disaster_monitor/infrastructure/weather/noaa_tsunami.py), [source documentation](docs/sources/noaa-tsunami-warnings.md) | Signature presence is retained; cryptographic verification is correctly not claimed. |
| 39 | Partial | [CAP lifecycle policy](apps/api/src/disaster_monitor/application/warnings/lifecycle.py) handles in-batch updates, cancels, references, expiry, duplicate syndication, and multilingual merge | Warning history is not persisted across feed pulls. An update/cancel whose ancestor has left the current feed cannot produce complete durable lifecycle history. |
| 40 | Partial | [association policy](apps/api/src/disaster_monitor/application/warnings/association.py) has explicit-ID and conservative time/geometry gates | The policy is used only by unit tests; no runtime use case records or presents associations. |
| 41 | Complete | [authority-first warning list](apps/web/src/features/weather/ui/AuthorityWarningList.tsx) filters source, event, severity, certainty, urgency, and state and displays issuer/validity | Data-age badge coverage remains part of task 22. |
| 42 | Partial | [spatial watch domain](apps/api/src/disaster_monitor/domain/spatial_watches.py) and [local store](apps/api/src/disaster_monitor/infrastructure/operations/local_spatial_watch_store.py) | Existing Incident Watch HTTP/UI supports country/worldwide scopes only; no spatial-watch composition, API, or UI exists. |
| 43 | Partial | Named point/polygon asset records exist in the spatial-watch domain/store | No operator CRUD workflow is wired. |
| 44 | Partial | [asset-exposure evaluator](apps/api/src/disaster_monitor/application/watches/evaluate_asset_exposure.py) retains source geometry/version and buffer policy | It is not invoked by workers and findings are not persisted or displayed. |
| 45 | Pending | A local state-store/payload helper exists in [web_push.py](apps/api/src/disaster_monitor/infrastructure/notifications/web_push.py) | No VAPID sender integration, HTTP subscription API, browser `PushManager` flow, service-worker push handler, or watch-delivery wiring exists. Existing documentation correctly calls external notifications unsupported. |
| 46 | Partial | [self-hosted ntfy adapter](apps/api/src/disaster_monitor/infrastructure/notifications/ntfy.py) rejects public `ntfy.sh` | No settings, composition, watch-delivery use case, retry diagnostics, or operator configuration path. |
| 47 | Partial | [deterministic digest builder](apps/api/src/disaster_monitor/application/watches/digest.py) groups the requested categories | No scheduler, persistence, API/UI, or delivery path. |
| 48 | Partial | [GloFAS adapter/domain](apps/api/src/disaster_monitor/infrastructure/hazard_context/copernicus.py) preserves issue/valid times and forecast role | Fixture-level adapter only; no selected-flood use case, composition, storage, API, or UI. |
| 49 | Partial | GDO drought episode/state parsing and a drought taxonomy entry exist | No live provider registration, slow-onset incident lifecycle/projection, API, or UI context path. |
| 50 | Partial | EFFIS/GWIS WMS context is represented with typed roles | No live layer registration, selected-wildfire workflow, or UI separation of detection/perimeter/danger/event. |
| 51 | Partial | [hazard taxonomy registry](apps/api/src/disaster_monitor/domain/hazards/taxonomy.py) centralizes aliases and warning mappings | Core event/query paths still depend on the closed `Disaster` enum and per-hazard policies; adding a hazard still requires coordinated code edits. CAP event types remain safely separate from physical events. |
| 52 | Partial | [OpenAerialMap STAC adapter](apps/api/src/disaster_monitor/infrastructure/ground_imagery/openaerialmap_stac.py) bounds event region/time and preserves creator/license fields | The adapter is not composed into Ground discovery or exposed in the API/UI. |
| 53 | Partial | Ground view provides matched-grid side-by-side/swipe pairing with capture dates and independent sensor status | It displays one static tile, does not expose coverage-mask overlays, and has no durable comparison resource or synchronized pan/zoom workflow. The UI now accurately labels this as display-only. |
| 54 | Partial | [comparison manifest builder](apps/api/src/disaster_monitor/application/ground_imagery/comparisons.py) records products, recipes, grid, masks, normalization, checksums, and metrics and now validates integrity strictly | No production use case, persistence, API route, or UI link creates/reads the manifest. |
| 55 | Partial | [export builder](apps/api/src/disaster_monitor/application/ground_imagery/exports.py) creates credential-free deterministic ZIPs and now verifies both COG checksums | No production API/job/UI path invokes it; preview generation and a real end-to-end export test remain absent. |

## P2 audit

| # | Status | Evidence | Remaining issue |
| ---: | --- | --- | --- |
| 56 | Partial | [GFM component extraction](apps/api/src/disaster_monitor/infrastructure/ground_imagery/gfm_regions.py) creates bounded connected regions with exact mask lineage and now validates SHA-256 syntax | No GFM acquisition/job path invokes the extractor or adds the resulting components to Ground incident context. |
| 57 | Partial | [CEMS delivered-product projection](apps/api/src/disaster_monitor/application/ground_imagery/impact_regions.py) distinguishes delineation, grading, and reference roles and retains activation/product version | It accepts an already-built product value; delivered product ingestion and Ground composition are absent. |
| 58 | Complete | [earthquake imagery context](apps/api/src/disaster_monitor/application/incidents/imagery_context.py) fetches USGS products for canonical USGS incidents, projects ShakeMap coverage, and is composed into Ground | Upstream products can still be unavailable, which correctly falls back to the base region evidence. |
| 59 | Complete | [direct public-COG renderer](apps/api/src/disaster_monitor/infrastructure/ground_imagery/local_products.py) is host-allowlisted, bounded, locally warps the selected product, and is composed as the renderer/fallback in [Ground construction](apps/api/src/disaster_monitor/infrastructure/composition_builders.py) | Large responses are bounded after HTTP receipt rather than by streamed transfer, so peak memory still follows the configured response limit. |
| 60 | Partial | [COG validation](apps/api/src/disaster_monitor/infrastructure/ground_imagery/raster_artifacts.py) checks grid bounds/CRS/transform and invokes [sensor-aware QA](apps/api/src/disaster_monitor/infrastructure/ground_imagery/raster_quality.py) for band order, masks, SCL, nodata masking, and radar noise | Exact two-raster alignment exists only as an uncomposed helper; no production analytical comparison path invokes it. |
| 61 | Partial | [geometry partition plans](apps/api/src/disaster_monitor/infrastructure/ground_imagery/geometry_partitioning.py) cover antimeridian, polar, and multi-UTM cases with deterministic merge rules | Ground grid planning/rendering does not consume these plans or execute/verify the merge. |
| 62 | Partial | [Sentinel-1 flood-change algorithm](apps/api/src/disaster_monitor/infrastructure/ground_imagery/analytics.py) is thresholded, versioned, quality-gated, and explicitly non-authoritative | No Ground job, artifact manifest, review store, API, or UI invokes/presents it. |
| 63 | Partial | The same [analytics module](apps/api/src/disaster_monitor/infrastructure/ground_imagery/analytics.py) provides versioned NBR change with cloud and coverage gates and non-grading language | It remains outside the production Ground workflow. |
| 64 | Partial | [analytical review domain](apps/api/src/disaster_monitor/domain/imagery/analysis.py) and [micro-review projection](apps/api/src/disaster_monitor/application/ground_imagery/micro_review.py) preserve immutable finding hashes beneath accept/reject/annotation decisions | There is no durable review repository, HTTP contract, or operator review UI. |
| 65 | Partial | [rights-gated MBTiles builder](apps/api/src/disaster_monitor/application/ground_imagery/offline_packages.py) creates deterministic local packages with attribution/license metadata | No selected-imagery packaging use case, API/job, package retention, or field-review UI is composed; PMTiles is not supported. |
| 66 | Complete | [service worker](apps/web/public/sw.js), generated [web manifest](apps/web/src/app/manifest.ts), and [bounded offline snapshots](apps/web/src/shared/model/offlineSnapshot.ts) cover the shell, incidents, source catalog, and findings with explicit offline/stale language | Browser storage remains best-effort and intentionally read-only. |
| 67 | Partial | The offline-package module can create a rights-gated baselayer MBTiles package with OSM attribution | The web map cannot open operator-provided PMTiles/MBTiles, and no documented local OSM tile-build/registration workflow was found. |
| 68 | Complete | [deterministic brief builder](apps/api/src/disaster_monitor/application/interoperability/incident_brief.py) and `/incidents/{id}/brief.html` render printable typed data, provenance, coverage, and gaps without a model | The brief is intentionally bounded to the active-incident projection and does not include every future context subsystem. |
| 69 | Complete | [GeoJSON/CSV exporters](apps/api/src/disaster_monitor/application/interoperability/exports.py) and HTTP routes export incidents, observations, and watch findings with identifiers, geometry meaning, times, source authority, and coverage | None found in the declared bounded projections after route review. |
| 70 | Complete | Ground exposes request-scoped [STAC catalog/item output](apps/api/src/disaster_monitor/presentation/http/ground_imagery_routes.py) for stored artifacts and source product/algorithm metadata | It is a narrow projection rather than a general STAC API, as intended. |
| 71 | Partial | [HXL-tagged CSV generation](apps/api/src/disaster_monitor/application/interoperability/exports.py) exists without adding HXL to the domain | No humanitarian/exposure use case or HTTP route constructs and exports these rows. |
| 72 | Complete | [read-only OGC Features-style projection](apps/api/src/disaster_monitor/application/interoperability/ogc_features.py) and routes expose incidents/observations with bounded bbox/time/limit queries; naive-time failure is fixed | The documentation correctly avoids claiming full OGC conformance. |
| 73 | Complete | [Atom feed projection](apps/api/src/disaster_monitor/application/interoperability/feeds.py) is exposed for durable Incident Watch timelines | RSS is not separately emitted, but Atom satisfies the requested open feed channel. |
| 74 | Partial | [typed provenance graph](apps/api/src/disaster_monitor/application/evidence/provenance_graph.py) and incident endpoint expose stable W3C-PROV-inspired nodes/edges | The runtime graph currently contains event/source/normalized evidence only; analytical artifact/finding/claim nodes and a visual frontend are absent. |
| 75 | Partial | [deterministic evidence trace](apps/api/src/disaster_monitor/application/evidence/why_evidence.py) and `/incidents/{id}/why` select admitted graph context before any model explanation | It is event-scoped rather than claim-scoped and is not registered as an assistant operation. |
| 76 | Complete | The model-free incident brief from task 68 is a usable first-pass brief and explicitly records its deterministic generator | None found in the bounded incident projection. |
| 77 | Complete | Assistant report transport retains the canonical `originalMessage`, [the UI exposes it on demand](apps/web/src/features/assistant/ui/AssistantEvidenceViews.tsx), and structured source records retain identifiers/authority names separately from localized prose | Provider payloads that never supply original-language text cannot manufacture it. |
| 78 | Complete | [multi-hazard validation](apps/api/src/disaster_monitor/application/agent/task_validation.py) builds up to four explicit hazard-country branches and [the sequential runtime](apps/api/src/disaster_monitor/application/agent/investigation_runtime.py) preserves country association and a shared budget | Ambiguous pairings and worldwide scope deliberately fail closed. |
| 79 | Complete | The same runtime supports two to four hazards, constructs branches in application code, and performs non-recursive pair assessment | The four-branch cap is deliberate and tested. |
| 80 | Complete | [active-incident query policy](apps/api/src/disaster_monitor/application/incidents/models.py) requires paired aware occurrence bounds, caps intervals at 366 days, versions snapshots, and exposes provider limitations | Multi-hazard Investigation Agent historical ranges remain separately unsupported. |
| 81 | Complete | [meaningful-change tracking](apps/api/src/disaster_monitor/application/incidents/meaningful_change.py), durable projection history, API view, and frontend controls distinguish change time from onset/publication time | None found in the bounded view. |
| 82 | Complete | [versioned compound rule registry](apps/api/src/disaster_monitor/application/evidence/event_policies/compound_hazard_correlation.py) declares rationale, exact temporal/spatial/geometry/observation gates, and non-causality language | Scientific/operational review remains necessary before adding rules. |
| 83 | Partial | [earthquake-to-tsunami warning policy](apps/api/src/disaster_monitor/application/warnings/association.py) prefers explicit identifiers and otherwise uses authoritative source, time, and geometry while denying occurrence inference | No warning/incident use case stores or presents the association. |
| 84 | Complete | The compound registry and [evaluation record](docs/p2-interoperability-and-provider-evaluations.md) keep cyclone/flood physical observations separate from forecast roles and describe only proximity | None found in the bounded rule. |
| 85 | Complete | [provider evaluation](docs/p2-interoperability-and-provider-evaluations.md) documents why VAAC admission was deferred and the required authority, IWXXM, geometry, lifecycle, and rights controls | A live VAAC source is intentionally not claimed. |
| 86 | Complete | The same evaluation documents why no additional live RSMC forecast was admitted and the normalization/ownership/rights gates required | A beyond-NHC live forecast is intentionally not claimed. |
| 87 | Partial | [source-candidate workbench](apps/api/src/disaster_monitor/application/sources/source_scouting.py) checks reachability, schema shape, and license availability while retaining human-only trust promotion | It has only in-memory/test composition; no durable workbench API, scheduled recheck, history, or UI exists. |
| 88 | Complete | [approved publisher registry](apps/api/src/disaster_monitor/infrastructure/news/resources/approved_publishers.v1.json), controlled fetcher/parser, worker composition, rights record, and default-registry test admit one bounded NASA feed | Live latency/recall promotion evidence remains absent, so no global detection claim is made. |
| 89 | Complete | [news candidate ingestion](apps/api/src/disaster_monitor/application/ingestion/news_candidates.py) clusters by normalized hazard/location tokens and UTC day while retaining every publisher source link and provisional authority | The deterministic heuristic can still over/under-cluster; cluster size is not used as truth authority. |
| 90 | Partial | Production parsers have malformed/missing-field fail-closed tests and [schema-drift policy](docs/schema-drift.md); one real Smithsonian before/after change is retained | The requested real older/current fixture pair for every parser does not exist; most coverage is authored inline boundary variation. |

## P3 audit

| # | Status | Evidence | Remaining issue |
| ---: | --- | --- | --- |
| 91 | Partial | [HDX HAPI adapter](apps/api/src/disaster_monitor/infrastructure/humanitarian/hdx_hapi.py) is rights/freshness bounded, conditionally composed, and exposed through the humanitarian-context API | Event Brief does not consume the returned indicators, so the stated brief improvement is not delivered. |
| 92 | Complete | [ReliefWeb adapter](apps/api/src/disaster_monitor/infrastructure/disaster/reliefweb_adapter.py) retains revision identity, themes, organizations, created/changed chronology, stale state, and explicit empty/no-report warnings | Live availability remains configuration/upstream dependent. |
| 93 | Complete | [IOM DTM adapter](apps/api/src/disaster_monitor/infrastructure/humanitarian/iom_dtm.py) is optional, conditionally composed, country/time/admin associated, and forbids causal displacement attribution | Dataset availability and exact licensing remain deployment/source dependent. |
| 94 | Partial | HDX operational-presence records and [humanitarian context service](apps/api/src/disaster_monitor/application/humanitarian/context.py) expose organization/sector/admin context with explicit endorsement/completeness limits | There is no operator map/context layer; the capability is API data only. |
| 95 | Complete | [`UnverifiedFieldReport`](apps/api/src/disaster_monitor/domain/field_reports.py) is separate from provider observations and requires times, channel, geometry/uncertainty, media lineage, authority, and review state | None found in the type boundary. |
| 96 | Complete | [desktop field-report workbench](apps/web/src/features/operations/ui/FieldReportWorkbench.tsx), API, privacy service, and durable stores support point/polygon, text, image, provenance, and visibly unverified defaults | The form intentionally supports one attachment per interactive submission although the API permits four. |
| 97 | Complete | [duplicate detector](apps/api/src/disaster_monitor/application/field_reports/duplicates.py), API, and UI produce time/space/type review candidates with `auto_merge=false` | Pair counts can grow quadratically at the bounded 500-report queue, but no automatic evidence merge occurs. |
| 98 | Complete | Field-report service/API/UI support reject, retain-unverified, associate, and separately policy-gated operator-observation admission with immutable review revisions | Operator identity is currently the configured local operator boundary. |
| 99 | Complete | [media privacy](apps/api/src/disaster_monitor/application/field_reports/media_privacy.py) strips JPEG/PNG metadata, blocks recognizable secrets/contact PII, records checksums/transforms/expiry, and [filesystem storage](apps/api/src/disaster_monitor/infrastructure/field_reports/filesystem_media_store.py) purges expired/corrupt/orphan content | Visible image content and all PII cannot be exhaustively classified; documentation states the human-review requirement. |
| 100 | Complete | [reviewed Kobo/ODK importer](apps/api/src/disaster_monitor/application/field_reports/importers.py) and API require explicit mapping/reviewer provenance, sanitize media, and never inherit external verification; import privacy validation is now preflighted before persistence | Store-capacity or I/O failure across a batch is not a transactional bulk-import boundary. |
| 101 | Complete | Optional Ushahidi import/export maps posts, categories, and location into unverified reports and emits `unverified_by_disastermonitor` | Media import is explicitly unsupported by this optional mapping. |
| 102 | Complete | [mapping workflow package](apps/api/src/disaster_monitor/application/interoperability/collaboration.py) and API create AOI GeoJSON plus HOT/MapSwipe outbound links without creating external tasks | None found in the bounded handoff. |
| 103 | Complete | Durable analyst notes/tags/bookmarks remain [non-evidence operator state](apps/api/src/disaster_monitor/application/operator_workspace/service.py), are labeled in exports, and are visibly separated in [the UI](apps/web/src/features/operations/ui/OperatorWorkspace.tsx) | None found in the declared boundary. |
| 104 | Complete | The same workspace provides local checklist/runbook templates with text references and `autonomous_actions=false`, exposed in API/UI | None found. |
| 105 | Complete | [evidence-package builder](apps/api/src/disaster_monitor/application/interoperability/evidence_packages.py) and API export deterministic ZIPs containing incident/source/data/findings/imagery/software/policy metadata with a SHA-256 manifest | Package contents are caller-selected; the API does not itself gather a canonical incident snapshot from all subsystems. |
| 106 | Complete | The verifier now rejects unsafe/duplicate/undeclared/oversized, hash-invalid, schema-invalid, non-JSON, shape-invalid, identity-inconsistent packages and always returns external/historical/non-merge state | Verification does not import package data into a browsing repository; it intentionally only verifies and classifies. |
| 107 | Partial | [local OSM adapter](apps/api/src/disaster_monitor/infrastructure/exposure/local_osm.py) calculates source age, feature count, named fraction, road/facility density, and explicit absence caveats | Exposure analysis is still uncomposed, so the indicators are not available through the selected-event API/UI. |
| 108 | Partial | [self-hosted OSRM adapter](apps/api/src/disaster_monitor/infrastructure/exposure/osrm.py), conditional composition, and `/access-context/routes` return bounded versioned route estimates with strong non-evacuation/non-safety language | No frontend route-visualization workflow consumes the path, so operators only have the raw API. |
| 109 | Partial | [critical-facility proximity service](apps/api/src/disaster_monitor/application/exposure/access_context.py) deterministically reports intersection/proximity with hazard and OSM lineage/data-age caveats | It is not composed with the local OSM provider and has no use case, route, or UI. |
| 110 | Complete | [locked field-report trust benchmark](evaluation/field_report_trust_benchmark.v1.json) covers external verification manipulation, sensitive misinformation, uncertain geolocation, and a 200-report volume cluster and asserts zero promotion/override/auto-merge/location invention | It is a trust-isolation benchmark, not a truth or geolocation-accuracy benchmark, as documented. |

## Remaining work in priority order

1. Replace the corpus summaries with exact, rights-approved raw payload snapshots for
   multiple recent and historical cases per hazard. Make adversarial identity cases
   executable and compute recall/merge/split/latency from actual adapter and identity
   outputs.
2. Run and record the four live Ground acceptance cases on the target machine, including
   artifact checksums, resource measurements, and expected desktop results.
3. Build the durable cross-subsystem incident timeline and extend claim inspection/data
   age semantics to Event Brief, warning, forecast, exposure, humanitarian, and imagery
   surfaces.
4. Compose exposure and hazard-context capabilities into selected-event use cases with
   durable typed evidence, HTTP contracts, and real Event Brief values.
5. Persist CAP history and wire conservative warning-to-incident association before
   calling lifecycle reconciliation complete.
6. Decide whether spatial/asset watches and local delivery are still in near-term scope.
   If so, add CRUD, worker evaluation, durable findings, VAPID/browser integration,
   self-hosted ntfy configuration, and scheduled digests. Do not advertise the current
   helper modules as delivered notification features.
7. Integrate OpenAerialMap and promote Ground comparisons/manifests/exports from isolated
   builders to one coherent, tested operator workflow.
8. Compose GFM/CEMS regions, difficult-geometry partition/merge, raster comparisons,
   analytical findings, human review, and licensed offline packaging into that same
   Ground workflow instead of leaving them as independent helpers.
9. Finish the interoperability surfaces that are only projections today: expose HXL
   from real humanitarian/exposure context, extend provenance through analytical
   artifacts/findings/claims, and add the visual/claim-scoped “why” workflow.
10. Make source scouting durable and operator-facing, add scheduled rechecks/history,
    and capture a real older/current fail-closed drift pair for every production parser.
11. Feed HDX/DTM/operational-presence context into the selected Event Brief and compose
    OSM completeness, critical-facility proximity, and route paths into bounded desktop
    context/visualization surfaces.
12. If field imports need all-or-nothing durability under storage/I/O failure, add a
    bulk transactional port. The current fix guarantees privacy preflight before the
    first report write but does not make arbitrary store failures transactional.

## Validation performed

- Provider-rights, replay, and Ground acceptance commands completed; Ground promotion
  correctly remained `pending` because all live cases are `not_run`.
- Backend unit suite after all fixes: 782 passed.
- Backend integration suite: 258 passed, 10 skipped (database/environment-dependent).
- Backend evaluation suite: 108 passed.
- Frontend suite after fixes: 175 passed.
- Focused red/green regression checks passed for provider rights, Ground comparison
  manifests/exports, Ground comparison UI wording, GFM checksum lineage, OGC time
  bounds, field-import privacy preflight, and evidence-package schema verification.
- Backend Ruff formatting/lint and both MyPy targets passed.
- Frontend Prettier, ESLint, TypeScript, API-contract freshness, and production build
  passed.

The fixes do not change live disaster retrieval, assistant routing, or local-model
behavior, so the repository's two-example live behavior smoke requirement was not
triggered.
