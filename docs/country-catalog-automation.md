# Autonomous country catalog updates

Disaster Monitor maintains a global, versioned country catalog without requiring a
human promotion step. Scheduled runs, browser requests, and the command-line script
use the same updater, so no trigger can bypass validation.

## Schedule and requests

The API starts a background scheduler when `COUNTRY_CATALOG_AUTOMATIC_UPDATES=true`.
It runs at 00:00 UTC on the first day of each month. If the API was stopped then and
has no successful update in the current month, it catches up at the next startup.
Failed attempts retain the active catalog and retry every
`COUNTRY_CATALOG_RETRY_HOURS` (six hours by default).

The **Evidence operations** panel shows the active version, country count, last
successful update, next automatic attempt, source versions, and a stable failure code.
**Update countries now** starts the same update path immediately.

The equivalent API operations are:

```text
GET  /api/v1/operations/country-catalog
POST /api/v1/operations/country-catalog/update
```

From the repository root, run or inspect the process without starting the web app:

```powershell
uv run --directory apps/api python scripts/update_country_catalog.py
uv run --directory apps/api python scripts/update_country_catalog.py --status
```

## Upstream authority and reproducibility

Network access is restricted to HTTPS on three allowlisted hosts:

- GitHub's API for the latest released `nvkelso/natural-earth-vector` tag and its
  immutable commit revision.
- `raw.githubusercontent.com` for Natural Earth 1:50m Admin 0 GeoJSON at that exact
  commit.
- IANA for `tzdata-latest.tar.gz`; the embedded tzdata version is validated before
  use.

Natural Earth and IANA tzdata are public domain. Every promoted catalog records the
upstream version, immutable revision, URL, SHA-256 checksum, and license. The generated
version is content-derived, so identical inputs cannot create a new catalog version.

## Fail-closed promotion

A candidate becomes active only when all of these checks pass:

1. Responses stay within registered HTTPS hosts and byte limits.
2. The Natural Earth release resolves to a 40-character commit and valid GeoJSON.
3. IANA provides a valid version and `zone.tab` with expected country coverage.
4. At least 190 unique, sorted alpha-3 country records are generated.
5. Preservation records for France, Japan, Türkiye, the United States, Venezuela, and
   Vietnam exist.
6. At least 95% of records retain polygon validation and at least 75% receive a
   deterministic IANA timezone.
7. Codes, bounds, coordinates, aliases, schema, and immutable-version collisions
   validate.

The candidate is stored as an immutable version and promoted with an atomic file
replacement. The in-memory catalog switches only after full payload validation. If
activation fails, the previous active bytes are restored. A process lock prevents
overlapping scheduled, browser, or script updates; stale locks expire after two hours.

Runtime files live under `COUNTRY_CATALOG_ROOT` (default `data/geography`):

```text
active.json                  # atomically promoted active catalog
update-status.json           # public update and retry state
catalogs/countries.*.json    # immutable generated versions
update.lock                  # short-lived cross-process lease
```

Compose mounts this directory as `country-catalog-data` for the API, scheduler, and
worker. Readers notice an atomic file revision and refresh without an app restart.

## Geographic and source limits

Admin 0 polygons are query approximations, not legal borders, maritime claims, or a
resolution of disputed sovereignty. Ambiguous aliases shared by multiple records are
removed. The default timezone is the IANA zone geographically closest to Natural
Earth's country label point; it is a deterministic calendar default, not proof that a
country has only one timezone.

Global country parsing does not imply global disaster evidence. Provider registration
still controls every disaster-country-role combination. Unsupported combinations remain
explicitly coverage-unavailable and cannot fall back to model-generated live claims.
