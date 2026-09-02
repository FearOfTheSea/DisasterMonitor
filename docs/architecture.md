# Architecture

This document maps the DisasterMonitor codebase. Detailed behavior belongs in the
subsystem documentation and source code.

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

Application owns use cases and defines the ports that it needs.

Infrastructure implements those ports and communicates with external systems.

Presentation translates HTTP requests and responses.

The composition boundary wires concrete dependencies.

`AppDependencyOverrides` is the typed composition input. The production bootstrap
can also accept a prebuilt `AppDependencies` container. Legacy individual test
overrides remain a thin compatibility facade.

Presentation constructs HTTP metrics. It supplies agent diagnostics through the
application-owned `AgentDiagnostics` protocol. Infrastructure never imports
presentation.

The side-effect-free HTTP shell in `presentation/http/api.py` registers the same
router and models as production. It is the only application factory for OpenAPI
generation. It does not construct infrastructure adapters or runtime resources.

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
