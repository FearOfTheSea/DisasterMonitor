# Provider rights and retention

The machine-readable source of truth is
`apps/api/src/disaster_monitor/infrastructure/sources/resources/provider_rights.v1.json`.
Every maintained source and selectable imagery layer has an entry. The API
loads and validates the manifest during composition; production entries may
use `public`, `free_account`, or `self_hosted` access, but never `paid`.

The manifest records authority, license, attribution, redistribution and cache
rules, bounded request/rate-limit policy, credential class, retention limit,
and the last human review date. A credential is acceptable only when it is a
free-account credential explicitly named in that entry. It is not evidence
that the upstream guarantees availability or unlimited use.

Source payloads are immutable, checksummed, source-attributed snapshots. Cache
retention is bounded per entry and deletion is represented by a tombstone in
the operational store. Derived Ground artifacts retain product IDs, recipe,
grid, checksum, and source attribution; they do not contain credentials.
