# Architecture.md

This document is the map of the DisasterMonitor codebase.

It describes where major components live and the boundaries between them. Detailed behavior belongs in the subsystem documentation and source code.

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

Dependency direction:

```text
presentation --> application --> domain

infrastructure adapters --> application contracts --> domain
```

- Domain contains core concepts and does not depend on frameworks or infrastructure.
- Application owns use cases and defines the ports it needs.
- Infrastructure implements those ports and communicates with external systems.
- Presentation translates HTTP requests and responses.
- Concrete dependencies are wired at the composition boundary.

The application surface available to infrastructure adapters is deliberately narrow:

- `application/ports/**`
- boundary data models in `application/agent/models.py`, `disaster.py`, `dto.py`,
  `media.py`, `multimodal.py`, `satellite_imagery.py`, and
  `source_intelligence.py`
- the visual-analysis prompt contract in `application/prompts/visual_analysis.py`

Ports include stable boundary normalization and admission primitives when both an
adapter and an application service must apply the same rule. Infrastructure adapters
must not import `application/services/**` or `application/use_cases/**`.

`infrastructure/composition.py`, `infrastructure/operations/runtime.py`, and
`main.py` are composition roots rather than adapters. They may import application
services and use cases solely to construct the object graph and process entry points.

Architecture boundaries are enforced by `apps/api/tests/unit/test_architecture_dependencies.py`.

## Frontend

```text
apps/web/src/

  app/             Next.js application and composition
  features/
    assistant/     Assistant UI and conversation behavior
    map/           Map UI and OpenLayers integration
    operations/    Operations UI
  shared/          Code shared across features
```

The frontend communicates with the backend through typed API clients. External disaster providers and Ollama are backend concerns.

## Tests

```text
apps/api/tests/
  unit/
  integration/
  evaluation/

apps/web/tests/
```

Tests follow the same architectural boundaries as production code.
