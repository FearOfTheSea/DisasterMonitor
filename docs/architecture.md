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
- The visual-analysis prompt contract in
  `application/prompts/visual_analysis.py`

Ports include stable boundary normalization and admission primitives when both an
adapter and an application service must apply the same rule.

Infrastructure adapters must not import `application/services/**` or
`application/use_cases/**`.

`infrastructure/composition.py`, provider-family modules under
`infrastructure/disaster/registrations/`, `infrastructure/operations/runtime.py`,
and `main.py` are composition roots. They are not adapters.

`infrastructure/app_dependencies.py` is the typed runtime container at that
boundary. These modules can import application services and use cases only to
construct or expose the object graph and process entry points.

Architecture boundaries are enforced by
`apps/api/tests/unit/test_architecture_dependencies.py`.

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
    map/           Map UI and OpenLayers integration
    operations/    Operations UI
    sources/       Read-only source-catalog projection
    weather/       Authoritative warning-artifact transport and UI
  shared/          Code shared across features
```

The frontend communicates with the backend through typed API clients. External
disaster providers and Ollama are backend concerns.

The application root owns bounded URL presentation state. It composes the existing
map, operations, source, and weather surfaces.

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

Architecture tests are executable design constraints. Change them only when an
intentional architecture decision updates this document and the software-quality
policy—not to accommodate a convenient dependency.
