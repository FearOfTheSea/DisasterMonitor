# Operational evidence runbook

## Country catalog automation

The API performs a catch-up-safe country update at 00:00 UTC on the first day of every
month and retries failures while retaining the last known-good catalog. Status and an
immediate request are available in the Evidence operations panel. For headless
operation and complete gate details, see
[Autonomous country catalog updates](../country-catalog-automation.md).

## Topology and authority

The production-like local topology is `web + api + scheduler + worker +
PostgreSQL/PostGIS + filesystem blob storage`. PostgreSQL is the durable job,
metadata, state, and audit store. Raw payloads are content-addressed files on a
separate volume. No Redis, Celery, Kafka, or Kubernetes dependency is introduced.

The scheduler enqueues enabled Incident Watches only when their persisted bounded
refresh time is due. The worker resolves each watch through the registered
event-discovery path and records deterministic observation/change state. It cannot
publish warnings, contact agencies, evacuate people, allocate resources, or expand
decision authority.

## Start and inspect

```powershell
docker compose config
docker compose up --build -d
docker compose ps
Invoke-RestMethod http://localhost:8001/api/v1/health
Invoke-RestMethod http://localhost:8001/api/v1/operations/providers
Invoke-RestMethod http://localhost:8001/api/v1/operations/evidence-history
Invoke-WebRequest http://localhost:8001/api/v1/metrics
```

The migration service must finish before the API, scheduler, and worker start. The
queue uses at-least-once delivery, `SKIP LOCKED`, bounded exponential retry, and a
dead-letter state. Snapshot and observation identities make duplicate delivery safe.
API and web runtime images run as dedicated non-root users. The API image is built from
the frozen uv lock graph used by CI, and the web runtime contains the Next.js standalone
output built from `package-lock.json`.

Without `OPERATIONAL_DATABASE_URL`, a standalone API uses an explicit in-process
metadata fallback and filesystem blobs for development. That metadata does not survive
restart and must not support an operational-continuity claim.

## Incident Watch operations

Create one worldwide watch from PowerShell:

```powershell
$watch = Invoke-RestMethod -Method Post `
  -Uri http://localhost:8001/api/v1/incident-watches `
  -ContentType application/json `
  -Body '{"disaster":"earthquake","scope":{"kind":"worldwide"},"refresh_interval_seconds":900}'
Invoke-RestMethod http://localhost:8001/api/v1/incident-watches
Invoke-RestMethod "http://localhost:8001/api/v1/incident-watches/$($watch.watch_id)/timeline"
```

Refresh intervals are limited to 300-86400 seconds. Enabling a disabled watch makes it
due immediately; disabling it prevents new jobs without deleting its timeline. Deleting
a watch removes its local observations, changes, and read state. The UI can mark
timeline entries read, but no external notification channel is configured.

For a due watch, inspect `ingest_job` rows with source
`incident-watch-refresh`, the watch's `last_checked_at`, `next_refresh_at`, and
`coverage_state`, then its newest-first change timeline. A retryable provider failure is
persisted as degraded coverage before the queue applies bounded retry.
Do not interpret `no_matching_records`, an observation gap, or unavailable coverage as
proof that an incident ended or did not occur.

## Freshness and degraded operation

The operations panel and API show `fresh`, `stale`, `unavailable`, or
`never_ingested`. Provider outage is not folded into API availability. Stale or missing
sources remain visible and cannot masquerade as current evidence. Configured-source
failures retry and then dead-letter. Unregistered scheduled identities fail closed.
The Prometheus-format endpoint reports low-cardinality request count, status, latency,
in-progress requests, queue counts by state, and optional agent-capability failures for
localization and contextual-media discovery. Detailed failures are logged while public
responses retain bounded fallback wording. The owner must choose and secure the actual
scraper, alert thresholds, log retention, and incident routing before pilot.

## Operator identity

`TRUSTED_OPERATOR_IDENTITY_ENABLED` is false by default. Enable it only behind a proxy
that strips client values and injects the authenticated ID using
`TRUSTED_OPERATOR_IDENTITY_HEADER`. The browser intentionally does not send this
header. The API rejects reviews if the boundary is disabled, identity is absent, or
the referenced world state does not exist.

An operator action records a bounded review and public rationale. It is not an external
action authorization and does not store model chain-of-thought.

## Backup and restore

Create a consistent database and blob backup:

```powershell
.\scripts\backup_operational.ps1
```

The script pauses writers, creates both archives, copies them under ignored
`data/backups/`, records SHA-256 checksums, and restarts services. Copy the set to
owner-approved encrypted storage.

Restore deliberately replaces operational state:

```powershell
.\scripts\restore_operational.ps1 `
  -BackupName 20260813-120000 `
  -ConfirmRestore REPLACE_OPERATIONAL_STATE
```

Exercise restore in a disposable environment before relying on a release. Compare
database counts, sample blob checksums, provider history, and deterministic replay.
Possessing scripts is not evidence that recovery passed.

## Retention

Production durations remain owner-approved policy. Code requires an exact source ID,
rights ID, positive duration, and public reason. The executor deletes only content and
preserves snapshot ID, checksum, timestamps, rights identity, and a tombstone. Raw user
prompts are not added to this operational store.

## Failure drills before pilot

Record drill evidence under ignored `data/experiments/`:

1. restart a worker after claim and confirm safe retry/no duplicate facts;
2. repeat a provider payload and confirm one logical snapshot;
3. replay out-of-order fixtures and confirm identical canonical output;
4. make a provider unavailable and confirm visible degradation;
5. stop Ollama and confirm bounded source-backed behavior;
6. restore a backup and compare counts/checksums;
7. verify forged identity headers are stripped by the deployed proxy;
8. rerun backend, frontend, evaluation, system, and Compose checks.
9. create a disposable watch, replay identical evidence, and confirm one logical alert;
10. force provider failure and recovery, confirm visible coverage transitions, bounded
    retry, and preservation of the previous successful observation baseline.
