# Architecture

This document maps the DisasterMonitor codebase. Detailed behavior belongs in the
subsystem documentation and source code.

## Architectural quality policy

Clean Architecture is a repository invariant. It is not deferred in order to deliver
faster and it is not weakened to make an implementation more convenient. Among valid
solutions, prefer the design that makes ownership, dependencies, and future changes
easiest to understand.

The repository-wide decision order and quality attributes are defined in
[software-quality.md](software-quality.md). This document defines how those priorities
map to concrete boundaries.

## Repository

```text
apps/
  api/          Backend application
  web/          Frontend application

docs/           Design and subsystem documentation
evaluation/     Evaluation data and tooling
scripts/        Repository and development scripts

compose.yaml    Local service orchestration
```

## Backend

```text
apps/api/src/disaster_monitor/

  domain/          Domain models and rules
  application/     Use cases, DTOs, and ports
  infrastructure/  External adapters and composition
  presentation/    HTTP and API boundary
  evaluation/      Evaluation support code
  main.py          FastAPI entry point
```

The dependency direction is:

```text
presentation --> application --> domain

infrastructure adapters --> application contracts --> domain
```

Domain contains core concepts. It does not depend on frameworks or infrastructure.
The stable `domain.disaster` module is an import facade; cohesive implementations live
in `disaster_types`, `events`, `evidence_types`, `evidence`, `triage`, and
`incident_watch`. Incident-watch canonical documents are isolated from the aggregate
models in `incident_watch_documents`.

Application owns use cases and defines the ports that it needs.

Infrastructure implements those ports and communicates with external systems.

Presentation translates HTTP requests and responses.

The composition boundary wires concrete dependencies.

These layers describe ownership, not folders alone. Put a rule in the layer responsible
for deciding it, even when another layer already has the required data. Do not duplicate
business policy at HTTP, persistence, provider, or UI boundaries for convenience.

The composition root is split by responsibility: `composition_models` owns typed
inputs, `composition_builders` owns focused adapter/service factories, and
`app_composition` assembles the complete runtime graph. `composition.py` remains a
stable import facade.

`AppDependencyOverrides` is the typed composition input. The production bootstrap
can also accept a prebuilt `AppDependencies` container. Legacy individual test
overrides remain a thin compatibility facade.

Presentation constructs HTTP metrics. It supplies agent diagnostics through the
application-owned `AgentDiagnostics` protocol. Infrastructure never imports
presentation.

The side-effect-free HTTP shell in `presentation/http/api.py` registers the same
router and models as production. It is the only application factory for OpenAPI
generation. It does not construct infrastructure adapters or runtime resources.

HTTP endpoints are grouped into system, catalog, incident, and assistant routers.
Request/response schemas and serializers follow the same resource boundaries;
`routes.py`, `schemas.py`, and `response_serialization.py` are compatibility and
composition facades only.

The application surface for infrastructure adapters is deliberately narrow:

- `application/ports/**`
- Boundary models in `application/agent/models.py`, `disaster.py`, `dto.py`,
  `media.py`, `multimodal.py`, `satellite_imagery.py`, `source_catalog.py`,
  `source_intelligence.py`, and `weather_alerts.py`
- `application/ports/ground_imagery/**` and the domain models under
  `domain/imagery/**`
- The visual-analysis prompt contract in
  `application/prompts/visual_analysis.py`

Ports include stable boundary normalization and admission primitives when both an
adapter and an application service must apply the same rule.

Infrastructure adapters must not import application capability implementations.
Only the contract surface listed above is available to adapters, regardless of
where a service is located. The architecture gate uses an allowlist rather than
relying on `services` or `use_cases` directory names.

`infrastructure/composition.py`, provider-family modules under
`infrastructure/disaster/registrations/`, `infrastructure/operations/runtime.py`,
and `main.py` are composition roots. They are not adapters.

`infrastructure/app_dependencies.py` is the typed runtime container at that
boundary. These modules can import application services and use cases only to
construct or expose the object graph and process entry points.

Architecture boundaries are enforced by
`apps/api/tests/unit/test_architecture_dependencies.py`.

## Application capabilities

Application implementations are organized by ownership rather than generic service
and use-case buckets. Each package contains its use cases and the deterministic
application helpers that change with them:

| Package | Ownership |
| --- | --- |
| `incidents` | Discovery, watch management, watch observation, change detection, priority coordination, map navigation |
| `evidence` | Admission, identity, reconciliation, geometry, immutable snapshots, retention, common operational picture |
| `investigation` | Report workflow, question routing, report rendering, specialist coordination, assistant request execution |
| `conversations` | Transcript turns and reads, bounded conversational context, historical-memory policy and recall |
| `ingestion` | Queue workers, schedules, watch dispatch, provider freshness, queue-status queries |
| `decision` | Options, hypotheses, scenarios, triage autonomy, attributable operator review |
| `sources` | Provider registry selection and source scouting |
| `media_analysis` | Media discovery and visual-analysis orchestration |
| `ground_imagery` | Event-scoped region/time planning, independent Sentinel-1/Sentinel-2 catalog selection, artifact preparation, provenance manifests, and Ground view status |
| `learning` | Offline learning, drift evaluation, governed optimization |
| `agent` | Bounded agent planning, execution, tools, and task validation |
| `ports` | Consumer-owned external seams and shared boundary admission rules |
| `compatibility` | Legacy construction only; no new use-case behavior |

`agent` and `investigation` collaborate as one execution subsystem; these are not
independently deployable services. Capability dependencies are explicitly checked in
`test_capability_boundaries.py`. Leaf decision, learning, and media-analysis packages
cannot acquire implementation dependencies on other capabilities. Evidence depends
on sources and agent boundary models; incidents depends on evidence and sources.
Conversation turns invoke the `AssistantResponder` port rather than a concrete
investigation use case. Shared assistant text admission lives beside that port.

Ground view consumes an `IncidentImageryContextReader` application port. Its resolver
owns region priority, fallback radii, geometry roles, and temporal policy; CDSE STAC,
Sentinel Hub Process, GeoBoundaries, raster validation, and artifact storage are
infrastructure adapters. The incident adapter projects already-admitted incident
geometry into that port and does not expose provider implementations inward. The
current deployment persists request metadata and selection mappings in PostgreSQL
when configured, with an in-process store for local development.

Incident retrieval is owned by `incidents/retrieval.py`. Interactive discovery in
`active_incidents.py` and watch projection in `watch_observation.py` consume that
same admitted retrieval result. Watch freshness, retryability, and observation
construction do not become rules of the interactive list.

Deterministic hazard-severity thresholds live in `domain/hazards/incident_priority.py`.
`domain/hazards/intensity.py` interprets the currently admitted notation once and
retains its scale. Ranking and priority remain separate decisions. Priority does
not treat JMA-labelled readings as MMI. This reorganization retains the existing
admission bounds rather than expanding supported intensity ranges or converting
between scales. Malformed labels no longer become ranking signals via substring
matches.

### Persistence and query ownership

Consumers request narrow ports: `IngestJobQueue`, `JobStatusReader`, `SnapshotReader`,
`SnapshotWriter`, `SnapshotRetentionStore`, `EvidenceWriter`, `OperatorActionStore`,
and `ProviderStatusReader`. `OperationalRepository` aggregates these only for runtime
composition and compatibility. The same concrete repository can satisfy several
ports; interface segregation does not require more database connections, changed
SQL, or split transactions. Incident-watch refresh remains one `record_watch_refresh`
operation, and conversation deletion retains its atomic deletion boundary.

The ingestion implementation is split into queue jobs, watch jobs, evidence snapshot
persistence, and decision review recording. Its old combined module is exports only.

HTTP transcript reads, evidence history, and queue metrics delegate to
`ConversationQueries`, `EvidenceHistoryQuery`, and `QueueStatusQuery`. Application
queries own query bounds and not-found outcomes; presentation owns transport parsing,
serialization, and HTTP error mapping. Conversation queries need only
`ConversationReader`, without transcript mutation authority.

### Investigation composition and compatibility

`DisasterInvestigationWorkflow` executes a report from an injected tool registry.
`build_investigation_resources` constructs providers, tool dependencies, workflow,
and infrastructure-owned shutdown hooks. API and worker composition consume those
resources directly. They never retrieve providers from a legacy report facade.

The original `application.services.current_disaster_report` import remains a pure
export. Legacy construction is isolated in `compatibility/report_composition.py`;
its execution delegates to the shared workflow. Existing injected legacy reports
are adapted once at composition. Production construction does not depend on that
legacy interface. The compatibility code can be removed when direct-construction
callers have migrated to explicit investigation resources.

## Module design

Modules should be cohesive around one responsibility and one reason to change. Public
interfaces should be narrow, explicit, and named in the language of the capability they
serve.

- Keep deterministic policy separate from I/O and orchestration.
- Keep provider-specific parsing and failure mapping inside the provider boundary.
- Keep composition limited to constructing and exposing the object graph.
- Centralize each invariant or mapping; do not copy it between layers.
- Use stable compatibility facades only for re-exports and composition.
- Review hand-maintained files above 500 LOC and split files above 700 LOC unless a
  documented cohesion exception applies.

File size is a diagnostic rather than an objective. A split must create a meaningful
ownership or dependency seam; excessive fragmentation is no more maintainable than a
monolith.

## Frontend

```text
apps/web/src/

  app/             Next.js application and composition
  features/
    assistant/     Assistant UI and conversation behavior
    commands/      Deterministic in-memory operator commands
    incidents/     Incident list and source-backed coverage
    map/           Map UI and OpenLayers integration
    operations/    Operations UI
    sources/       Read-only source-catalog projection
    weather/       Authoritative warning-artifact transport and UI
  shared/          Code shared across features
```

The frontend communicates with the backend through typed API clients. External
disaster providers and Ollama are backend concerns.

The application root composes map, operations, source, and weather surfaces.
`app/workspace/useMapWorkspace` owns map selection and presentation state;
`useWorkspaceUrlState` owns browser-history synchronization and cleanup;
`useWorkspacePanels` owns a single exclusive panel state and requested heading focus.
The page renders those states and coordinates feature actions.

Cross-feature imports use explicit `public.ts` contracts. A public contract exports
only capabilities consumed by other features; it does not re-export a feature's
entire UI. Application composition may import feature entry points directly. Shared
modules cannot import features or app code, and features cannot import app code.
The shared display-time-window contract avoids a map/incident dependency cycle.
ESLint enforces these boundaries, including relative imports. Frontend architecture
tests reject cycles between features, including type-only dependencies.

Feature-owned UI styling lives beside the feature that changes it. Shared shell,
panel, and responsive rules remain under `app/`; the root layout imports these style
modules in explicit cascade order. `globals.css` is limited to design tokens, resets,
and application-shell primitives rather than serving as a cross-feature stylesheet.

Weather alerts use a dedicated application port and infrastructure adapter. They do
not enter the disaster-provider registry or the physical-event domain.

Generated frontend contract output includes TypeScript types and backend OpenAPI
component schemas for runtime structural validation.

Handwritten client validation covers only semantic, cross-field, provenance, and
geometry invariants.

## Tests

```text
apps/api/tests/
  unit/
  integration/
  evaluation/

apps/web/tests/
```

Tests follow the same architectural boundaries as production code.

Backend import checks resolve relative imports, restrict application imports to the
standard library and inward layers, and protect compatibility facades from growing
implementations. Frontend tests parse imports and exports with TypeScript.

Architecture tests are executable design constraints. Change them only when an
intentional architecture decision updates this document and the software-quality
policy—not to accommodate a convenient dependency.
