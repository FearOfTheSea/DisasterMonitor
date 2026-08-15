# Roadmap 2 implementation status

This implementation advances `deep-research-report-41bcc77.md` while preserving
fail-closed external promotion gates.

| Workstream | Implemented engineering surface | Remaining non-code gate |
|---|---|---|
| Evidence/evaluation | DisasterAgentBench manifest validation, hidden-label separation, integrity-only run, default fail-closed release evaluation, deterministic hashes, replay entry point, experiment ledger | Licensed frozen corpus, external labels, final metric run, real model/hardware record |
| Source coverage | NCHMF flood/landslide/cyclone, FIRMS active fire, GFM flood product, constructor-bound CAP adapter; executable registry/catalog coverage and source-policy checks | Credentials, rights evidence, reviewed CAP registrations, independent historical corpora |
| Temporal operations | PostgreSQL/PostGIS migration, immutable blobs/snapshots, idempotent jobs, scheduler/workers, snapshot-linked observations, versioned world state, freshness, audit, retention tombstones, deterministic replay | Long-duration restart/replay/retention drills on approved data |
| Product/deployment | Production-like Compose topology, migration gate, status/history API and UI, trusted-identity review boundary, backup/restore tools and runbook | TLS/auth proxy, monitored hosting, secrets system, successful restore drill, 30-day supervised pilot |
| Human evaluation | Protocol expectations and fail-closed release reporting | Ethics determination, recruitment, blinded studies, legitimate results |

No release result, study participant, dataset permission, baseline tag, model digest,
backup exercise, or pilot outcome has been fabricated. See
[project-owner-actions.md](project-owner-actions.md) for the authoritative handoff.

## Local verification evidence

On 2026-08-13, the disposable Compose verification migrated both operational schema
versions, returned nine provider records and 15 snapshot-history records, rejected an
untrusted operator identity, and persisted a live JMA reconciliation as normalized
observations, event links, a physical event, and a versioned world state. A quiescent
backup/restore smoke retained the database count tuple `17,15,2` for snapshots,
observations, and world states. This is local engineering evidence only; it does not
replace an owner-controlled deployment recovery drill or any normative release gate.
