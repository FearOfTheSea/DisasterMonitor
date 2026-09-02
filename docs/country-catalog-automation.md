# Autonomous country catalog updates

Disaster Monitor maintains a global, versioned country catalog without a human
promotion step. Scheduled runs, browser requests, and the command-line script use
the same updater. No trigger can bypass validation.

## Schedule and requests

The API starts a background scheduler when
`COUNTRY_CATALOG_AUTOMATIC_UPDATES=true`.

The scheduler runs at 00:00 UTC on the first day of each month. If the API was
stopped at that time and has no successful update during the current month, it
catches up at the next startup.

Failed attempts keep the active catalog. The updater retries every
`COUNTRY_CATALOG_RETRY_HOURS`; the default is six hours.

The **Evidence operations** panel shows the active version, country count, last
successful update, next automatic attempt, source versions, and stable failure code.
The **Update countries now** action starts the same update path immediately.

The equivalent API operations are:

```text
GET  /api/v1/operations/country-catalog
POST /api/v1/operations/country-catalog/update
```

Run or inspect the process from the repository root without starting the web app:

```powershell
uv run --directory apps/api python scripts/update_country_catalog.py
uv run --directory apps/api python scripts/update_country_catalog.py --status
```

## Upstream authority and reproducibility

Network access is restricted to HTTPS on three allowlisted hosts:

- GitHub API for the latest released `nvkelso/natural-earth-vector` tag and its
  immutable commit revision.
- `raw.githubusercontent.com` for Natural Earth 1:50m Admin 0 GeoJSON at that
  exact commit.
- IANA for `tzdata-latest.tar.gz`; the updater validates the embedded tzdata version.

Natural Earth and IANA tzdata are public domain. Each promoted catalog records the
upstream version, immutable revision, URL, SHA-256 checksum, and license.

The generated version is content-derived. Identical inputs cannot create a new
catalog version.

## Fail-closed promotion

A candidate becomes active only when all checks pass:

1. Keep responses within registered HTTPS hosts and byte limits.
2. Resolve the Natural Earth release to a 40-character commit and valid GeoJSON.
3. Confirm valid IANA version data and `zone.tab` with expected country coverage.
4. Generate at least 190 unique, sorted alpha-3 country records.
5. Keep preservation records for France, Japan, Türkiye, the United States,
   Venezuela, and Vietnam.
6. Keep polygon validation for at least 95% of records and a deterministic IANA
   timezone for at least 75% of records.
7. Validate codes, bounds, coordinates, aliases, schema, and immutable-version
   collisions.

Store the candidate as an immutable version. Promote it with an atomic file
replacement. Switch the in-memory catalog only after full payload validation.

If activation fails, restore the previous active bytes. A process lock prevents
overlapping scheduled, browser, and script updates. Stale locks expire after two
hours.

Runtime files live under `COUNTRY_CATALOG_ROOT`, which defaults to
`data/geography`:

```text
active.json                  # atomically promoted active catalog
update-status.json           # public update and retry state
catalogs/countries.*.json    # immutable generated versions
update.lock                  # short-lived cross-process lease
```

Compose mounts this directory as `country-catalog-data` for the API, scheduler, and
worker. Readers detect an atomic file revision and refresh without an app restart.

## Geographic and source limits

Admin 0 polygons are query approximations. They are not legal borders, maritime
claims, or a resolution of disputed sovereignty.

Remove ambiguous aliases that are shared by multiple records.

The default timezone is the IANA zone geographically closest to Natural Earth’s
country label point. It is a deterministic calendar default, not proof of one
timezone per country.

Global country parsing does not imply global disaster evidence. Provider registration
still controls every disaster-country-role combination.

Unsupported combinations remain explicitly coverage-unavailable. They cannot use
model-generated live claims as a fallback.
