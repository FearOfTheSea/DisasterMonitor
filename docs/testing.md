# Testing

DisasterMonitor tests protect behavior, architecture, and research reproducibility.

The default rule is:

`deterministic tests first; live systems supplement them`

Features and fixes follow Red → Green → Refactor. Write the expected behavior as a test first, confirm the failure is meaningful, then implement the smallest complete change.

## Principles

- Test observable behavior, not implementation details.
- Prefer fakes at application ports over patching internal functions.
- Keep automated tests deterministic and independent of live providers or model output.
- Every bug fix includes a regression test for the failed behavior.
- Cover important failure and boundary cases, not only happy paths.
- Treat architecture tests as quality gates. Do not weaken them to make code fit.
- Treat flaky tests as defects. Remove the source of nondeterminism instead of retrying until green.
- Keep fixtures local unless they represent a genuinely shared concept.
- Name tests after the rule or behavior they protect.

Qwen and live disaster providers validate real integrations. They do not replace deterministic automated tests.

## Test layers

Backend tests live under:

```text
apps/api/tests/
  unit/
  integration/
  evaluation/
```

Frontend tests live under:

```text
apps/web/tests/
```

Additional system and live-smoke checks live under `apps/web/scripts/` and `scripts/`.

### Unit

Unit tests cover domain rules, application services, use cases, validation, and deterministic policy.

They should not require network access, a database, Ollama, or other external services. Use fakes for application ports.

Architecture dependency checks are unit-level quality gates.

### Integration

Integration tests cover boundaries where DisasterMonitor communicates with another component or representation.

Examples:

- HTTP routes and schemas
- disaster-provider adapters
- serialization and parsing
- persistence repositories and migrations
- model and vision adapters

External provider behavior should normally be tested with representative fixture payloads. Persistence behavior should be tested against the real database engine when database semantics matter.

### Frontend

Frontend tests cover client logic and user-visible behavior.

- Pure model and validation logic uses Vitest unit tests.
- React behavior uses Testing Library.
- API clients test transport, validation, and failure handling at the client boundary.

Prefer user-observable assertions over component implementation details.

### System

System tests exercise critical operator workflows through the built frontend and backend.

They use controlled data and deterministic dependencies. Keep scenarios focused enough that a failure identifies the broken workflow.

### Evaluation

Evaluation tests measure disaster-monitoring and agent quality against fixed datasets and benchmark cases.

Keep evaluation metrics separate from conventional software correctness. A benchmark improvement does not replace unit, integration, or system coverage.

### Live smoke

Live smoke checks exercise real Qwen or external providers.

They are useful before releases, demonstrations, and model-facing changes. They must not be the only evidence that a behavior works and should not determine normal CI success.

## Change requirements

Use the smallest test layer that proves the behavior, then add boundary coverage when the change crosses a boundary.

- Domain rule or value object: unit tests, including boundary and invalid cases.
- Application service or use case: unit tests with fake ports.
- Bug fix: failing regression test first.
- Disaster-provider adapter: fixture-based integration tests plus provider failure cases.
- HTTP endpoint or schema: HTTP integration tests.
- Repository or SQL migration: integration tests against the real database engine.
- Frontend pure logic: Vitest unit tests.
- React interaction: Testing Library component tests.
- Backend/frontend contract change: backend HTTP coverage and frontend client or validation coverage.
- Critical operator workflow: system test.
- Agent or model-facing behavior: deterministic fake-model tests and relevant evaluation coverage; run Qwen when relevant.

Do not add a broader test only because it is easier to write. Prefer the narrowest test that clearly expresses the requirement.

## Commands

Backend:

```powershell
uv run --directory apps/api pytest tests/unit -q
uv run --directory apps/api pytest tests/integration -q
uv run --directory apps/api pytest tests/evaluation -q
uv run --directory apps/api pytest -q
uv run --directory apps/api ruff format --check src tests
uv run --directory apps/api ruff check src tests
uv run --directory apps/api mypy
```

Frontend:

```powershell
cd apps/web
npm run check:api-contract
npm run format:check
npm run lint
npm run typecheck
npm test
npm run build
npm run test:system
```

The backend OpenAPI document is the assistant transport-contract authority. After an
HTTP schema change, run `npm run generate:api-contract` in `apps/web` and commit the
generated types and runtime schemas. `check:api-contract` regenerates in memory and
fails when the committed contract is stale; handwritten frontend validation remains
responsible only for semantic and cross-record invariants.

During Red and Green, run the narrowest relevant test. Before completing a substantial change, run the relevant static checks and affected suites. CI remains the full repository gate.

## CI

CI runs backend and frontend checks independently, then runs the system test after both succeed.

Normal CI should remain deterministic. Live provider and Qwen smoke checks are supplemental unless explicitly promoted to a separate release gate.

CI and the API container install the frozen `apps/api/uv.lock` graph. Frontend CI and
containers use `npm ci` with `apps/web/package-lock.json`; release-critical Node and uv
versions are pinned in the workflow and Dockerfiles.
CI builds both final runtime images, imports `disaster_monitor` from the API image, and
polls the containerized health endpoint without Ollama or external providers.

Coverage is a diagnostic, not the goal. If coverage reporting is introduced, use it to find untested behavior and prevent meaningful regressions rather than optimizing for a percentage alone.

## Definition of done

A software change is complete when:

- intended behavior is covered at the appropriate layer
- fixes and features demonstrated the expected Red state when applicable
- important boundary and failure behavior is covered
- tests do not depend on uncontrolled live systems
- architecture constraints still pass
- relevant formatting, linting, type checking, tests, and builds pass
- affected contracts and documentation are updated

A passing test suite is necessary but not sufficient. Tests should make future changes safer and failures easier to understand.
