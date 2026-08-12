# Migration report

This is a historical migration snapshot, not current capability or release evidence.
Its command outputs and dependency findings describe the original migration run. See
[Capability and promotion status](capability-status.md) for the audited current state.

## Sources inspected

- `.migration-sources/Disaster-monitor-be-main/Disaster-monitor-be-main/`
- `.migration-sources/Disaster-monitor-fe-main/Disaster-monitor-fe-main/`
- `.migration-sources/ScholarAgent-main/ScholarAgent-main/`

All three source directories were inspected before implementation. They remain read-only and are ignored by the destination repository.

## Useful behavior retained or adapted

- The backend's local Ollama configuration and Qwen default (`qwen3:1.7b`) were retained, with a smaller direct adapter around Ollama's local `/api/chat` and `/api/tags` endpoints.
- The original frontend's OpenLayers base map, Hanoi center (`105.85, 21.03`), and zoom 10 were retained.
- The source assistant flow's concise user-facing response goal and reasoning-leak cleanup were adapted into deterministic application-layer prompt preparation and response cleanup.
- ScholarAgent's provider-neutral LLM port, explicit composition root, local Ollama approach, health/readiness separation, and fake-adapter testing style informed the new boundaries.

## Behavior intentionally dropped or deferred

The legacy weather, geocoding, satellite catalog and imagery, flood-analysis, image-generation, database session, multi-agent tool routing, remote provider, authentication, and deployment integrations were not copied. Several were incomplete, credential-dependent, network-dependent, or too broad for a reliable local MVP. The new UI does not expose active controls that pretend those integrations work.

The API keeps only browser-session conversation continuity. Server-side persistence and multi-user state are deferred.

## Architecture decisions

- One `LanguageModel` port is sufficient for the current request and readiness flows.
- Ollama-specific payloads and timeout behavior stay in `OllamaQwenAdapter`.
- Manual dependency construction keeps the vertical slice visible without a DI framework.
- The frontend separates transport, conversation state, session storage, map construction, and presentation.
- The system test uses a fake model behind the real FastAPI application and real Next.js UI.

## Checks actually executed

The counts below are intentionally preserved as historical evidence and must not be
read as current test totals.

- Backend formatting: `uv run ruff format --check src tests` passed in `apps/api` (27 files already formatted).
- Backend lint: `uv run ruff check src tests` passed in `apps/api`.
- Backend type check: `uv run mypy` passed in `apps/api`.
- Backend unit, HTTP integration, and adapter tests: `uv run pytest -q` passed, 10 tests.
- Frontend formatting: `npm run format:check` passed.
- Frontend lint: `npm run lint` passed with no errors or warnings after the final config cleanup.
- Frontend type check: `npm run typecheck` passed.
- Frontend unit/component tests: `npm test` passed, 6 tests.
- Frontend production build: `npm run build` passed.
- Deterministic system test: `npm run test:system` passed; the fake FastAPI model response appeared in the production Next.js UI through a headless Chromium browser.
- Optional real-Qwen smoke test: `ollama list` found `qwen3:1.7b`, and `uv run --project apps/api python scripts/real_qwen_smoke.py` passed against a locally started API. The response was produced by the local model, not a hosted provider.
- Migration-source tracking audit: `git ls-files .migration-sources` produced no output.
- Secret/generated-file audit: staged-content review and repository scans found no committed credentials or generated runtime artifacts.

## Checks not run and limitations

The limitations below are also historical. Current Docker, dependency-audit, and gate
results belong in the current verification record, not this migration snapshot.

- Compose validation was not run because Docker Desktop / the `docker` command is not installed in this environment. The Compose file and Dockerfiles are included but were not claimed as runtime-tested.
- OpenStreetMap tile availability was not treated as a CI dependency; browser tests verify the application flow without asserting remote tile content.
- The real-Qwen smoke test is documented and was run locally once, but it remains excluded from default CI because Ollama and model weights are machine-local.
- `npm install` reported three high-severity transitive audit findings from the current dependency tree. No `npm audit fix --force` was applied because it could change the selected Next.js toolchain outside the MVP scope.

## Source tracking confirmation

Before commit, `git ls-files .migration-sources` must produce no output. `AGENTS.md` is also intentionally ignored and is not committed.
