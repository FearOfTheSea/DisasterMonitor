# Testing

DisasterMonitor tests protect behavior, architecture, and research reproducibility.

Use this rule:

`deterministic tests first; live systems supplement them`

Follow Red → Green → Refactor for features and fixes. Write the expected behavior as
a test first. Confirm a meaningful failure. Implement the smallest complete change.

## Principles

- Test observable behavior, not implementation details.
- Prefer fakes at application ports over patches to internal functions.
- Keep automated tests deterministic and independent of live providers and model output.
- Add a regression test for every bug fix.
- Cover important failure and boundary cases, not only successful cases.
- Treat architecture tests as quality gates. Do not weaken them.
- Treat flaky tests as defects. Remove nondeterminism instead of retrying.
- Keep fixtures local unless they represent a genuinely shared concept.
- Name tests after the rule or behavior that they protect.

Qwen and live disaster providers validate real integrations. They do not replace
deterministic automated tests.

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

Unit tests cover domain rules, application services, use cases, validation, and
deterministic policy.

They must not require network access, a database, Ollama, or another external
service. Use fakes for application ports.

Architecture dependency checks are unit-level quality gates.

### Integration

Integration tests cover boundaries where DisasterMonitor communicates with another
component or representation.

Examples include:

- HTTP routes and schemas
- disaster-provider adapters
- serialization and parsing
- persistence repositories and migrations
- model and vision adapters

Test external provider behavior with representative fixture payloads in most cases.
Test persistence against the real database engine when database semantics matter.

### Frontend

Frontend tests cover client logic and user-visible behavior.

- Use Vitest unit tests for pure model and validation logic.
- Use Testing Library for React behavior.
- Test API clients at the client boundary for transport, validation, and failure handling.

Prefer assertions about user-observable behavior over component implementation details.

### System

System tests exercise critical operator workflows through the built frontend and
backend.

Use controlled data and deterministic dependencies. Keep each scenario focused so a
failure identifies the broken workflow.

### Evaluation

Evaluation tests measure disaster-monitoring and agent quality against fixed datasets
and benchmark cases.

Keep evaluation metrics separate from conventional software correctness. Benchmark
improvement does not replace unit, integration, or system coverage.

### Live smoke

Live smoke checks exercise real Qwen or external providers.

Use them before releases, demonstrations, and model-facing changes. Do not use them
as the only evidence that behavior works. Do not use them to determine normal CI success.

## Change requirements

Use the smallest test layer that proves the behavior. Add boundary coverage when the
change crosses a boundary.

- Domain rule or value object: use unit tests, including boundary and invalid cases.
- Application service or use case: use unit tests with fake ports.
- Bug fix: write a failing regression test first.
- Disaster-provider adapter: use fixture-based integration tests and provider failure cases.
- HTTP endpoint or schema: use HTTP integration tests.
- Repository or SQL migration: use integration tests against the real database engine.
- Frontend pure logic: use Vitest unit tests.
- React interaction: use Testing Library component tests.
- Backend/frontend contract change: use backend HTTP coverage and frontend client or
  validation coverage.
- Critical operator workflow: use a system test.
- Agent or model-facing behavior: use deterministic fake-model tests and relevant
  evaluation coverage; run Qwen when relevant.

Do not add a broader test only because it is easier to write. Use the narrowest test
that clearly expresses the requirement.

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

The backend OpenAPI document is the assistant transport-contract authority.

After an HTTP schema change, run `npm run generate:api-contract` in `apps/web`.
Commit the generated types and runtime schemas.

`check:api-contract` regenerates in memory and fails when the committed contract is
stale.

Handwritten frontend validation remains responsible only for semantic and cross-record
invariants.

During Red and Green, run the narrowest relevant test. Before completing a substantial
change, run relevant static checks and affected suites.

CI remains the full repository gate.

## CI

CI runs backend and frontend checks independently. It runs the system test after both
checks succeed.

Normal CI remains deterministic. Live provider and Qwen smoke checks are supplemental
unless a separate release gate promotes them.

CI and the API container install the frozen `apps/api/uv.lock` graph.

Frontend CI and containers use `npm ci` with `apps/web/package-lock.json`.
Release-critical Node.js and uv versions are pinned in workflows and Dockerfiles.

CI builds both final runtime images. It imports `disaster_monitor` from the API image
and polls the containerized health endpoint without Ollama or external providers.

Coverage is a diagnostic, not the goal. If coverage reporting is introduced, use it to
find untested behavior and prevent meaningful regressions.

## Definition of done

A software change is complete when:

- intended behavior has coverage at the appropriate layer;
- applicable fixes and features demonstrated the expected Red state;
- important boundary and failure behavior has coverage;
- tests do not depend on uncontrolled live systems;
- architecture constraints still pass;
- relevant formatting, linting, type checking, tests, and builds pass; and
- affected contracts and documentation are updated.

A passing test suite is necessary but not sufficient. Tests should make future changes
safer and failures easier to understand.
