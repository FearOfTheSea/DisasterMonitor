# Operational evidence runbook

## Country catalog automation

The API performs a catch-up-safe country update at 00:00 UTC on the first day of each
month. It retries failures and retains the last known-good catalog.

The Evidence operations panel shows status and supports an immediate request. See
[Autonomous country catalog updates](../country-catalog-automation.md) for headless
operation and gate details.

## Topology and authority

The production-like local topology is `web + api + scheduler + worker +
PostgreSQL/PostGIS + filesystem blob storage`.

PostgreSQL stores durable jobs, metadata, state, and audit data. Raw payloads are
content-addressed files on a separate volume.

The topology has no Redis, Celery, Kafka, or Kubernetes dependency.

The scheduler enqueues enabled Incident Watches only when their persisted bounded
refresh time is due.

The worker resolves each watch through the registered event-discovery path and records
deterministic observation and change state.

It cannot publish warnings, contact agencies, evacuate people, allocate resources, or
expand decision authority.

## Start and inspect

Run these commands:

```powershell
docker compose config
docker compose up --build -d
docker compose ps
Invoke-RestMethod http://localhost:8001/api/v1/health
Invoke-RestMethod http://localhost:8001/api/v1/operations/providers
Invoke-RestMethod http://localhost:8001/api/v1/operations/evidence-history
Invoke-WebRequest http://localhost:8001/api/v1/metrics
```

Wait for the migration service to finish before the API, scheduler, and worker start.

The queue uses at-least-once delivery, `SKIP LOCKED`, bounded exponential retry, and a
dead-letter state.

Snapshot and observation identities make duplicate delivery safe.

API and web runtime images run as dedicated non-root users.

The API image uses the frozen uv lock graph used by CI. The web runtime uses the
Next.js standalone output built from `package-lock.json`.

Without `OPERATIONAL_DATABASE_URL`, a standalone API uses an explicit in-process
metadata fallback and filesystem blobs for development.

That metadata does not survive restart. Do not use it to support an
operational-continuity claim.

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

Refresh intervals are limited to 300–86400 seconds.

Enabling a disabled watch makes it due immediately. Disabling it prevents new jobs
without deleting its timeline.

Deleting a watch removes its local observations, changes, and read state.

The UI can mark timeline entries read. No external notification channel is configured.

For a due watch, inspect `ingest_job` rows with source `incident-watch-refresh`.

Inspect the watch’s `last_checked_at`, `next_refresh_at`, and `coverage_state`.

Inspect its newest-first change timeline.

A retryable provider failure is persisted as degraded coverage before the queue applies
bounded retry.

Do not interpret `no_matching_records`, an observation gap, or unavailable coverage as
proof that an incident ended or did not occur.

## Freshness and degraded operation

The operations panel and API show `fresh`, `stale`, `unavailable`, or `never_ingested`.

Provider outage is not folded into API availability.

Stale or missing sources remain visible. They cannot appear as current evidence.

Configured-source failures retry and then enter dead-letter state.

Unregistered scheduled identities fail closed.

The Prometheus-format endpoint reports low-cardinality request count, status, latency,
in-progress requests, queue counts by state, and optional agent-capability failures for
localization and contextual-media discovery.

Detailed failures are logged. Public responses retain bounded fallback wording.

Before a pilot, the owner must choose and secure the scraper, alert thresholds, log
retention, and incident routing.

## Operator identity

`TRUSTED_OPERATOR_IDENTITY_ENABLED` is false by default.

Enable it only behind a proxy that strips client values and injects the authenticated
ID through `TRUSTED_OPERATOR_IDENTITY_HEADER`.

The browser intentionally does not send this header.

The API rejects reviews when the boundary is disabled, identity is absent, or the
referenced world state does not exist.

An operator action records a bounded review and public rationale. It is not external
action authorization and does not store model chain-of-thought.

## Backup and restore

Create a consistent database and blob backup:

```powershell
.\scripts\backup_operational.ps1
```

The script pauses writers, creates both archives, copies them under ignored
`data/backups/`, records SHA-256 checksums, and restarts services.

Copy the set to owner-approved encrypted storage.

Restore deliberately replaces operational state:

```powershell
.\scripts\restore_operational.ps1 `
  -BackupName 20260813-120000 `
  -ConfirmRestore REPLACE_OPERATIONAL_STATE
```

Exercise restore in a disposable environment before relying on a release.

Compare database counts, sample blob checksums, provider history, and deterministic
replay.

Possessing scripts is not evidence that recovery passed.

## Retention

Production durations remain owner-approved policy.

Code requires an exact source ID, rights ID, positive duration, and public reason.

The executor deletes only content. It preserves snapshot ID, checksum, timestamps,
rights identity, and a tombstone.

Raw user prompts are not added to this operational store.

## Failure drills before pilot

Record drill evidence under ignored `data/experiments/`.

1. Restart a worker after claim. Confirm safe retry and no duplicate facts.
2. Repeat a provider payload. Confirm one logical snapshot.
3. Replay out-of-order fixtures. Confirm identical canonical output.
4. Make a provider unavailable. Confirm visible degradation.
5. Stop Ollama. Confirm bounded source-backed behavior.
6. Restore a backup. Compare counts and checksums.
7. Verify that the deployed proxy strips forged identity headers.
8. Rerun backend, frontend, evaluation, system, and Compose checks.
9. Create a disposable watch. Replay identical evidence and confirm one logical alert.
10. Force provider failure and recovery. Confirm visible coverage transitions, bounded
    retry, and preservation of the previous successful observation baseline.
