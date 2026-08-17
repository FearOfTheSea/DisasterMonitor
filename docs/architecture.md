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

Backend source lives in:

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

infrastructure --> application ports
```

- Domain contains core concepts and does not depend on frameworks or infrastructure.
- Application owns use cases and defines the ports it needs.
- Infrastructure implements those ports and communicates with external systems.
- Presentation translates HTTP requests and responses.
- Concrete dependencies are wired at the composition boundary.

Architecture boundaries are enforced by `apps/api/tests/unit/test_architecture_dependencies.py`.

## Frontend

Frontend source lives in:

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