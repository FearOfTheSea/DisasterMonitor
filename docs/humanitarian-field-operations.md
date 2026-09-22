# Humanitarian context and field operations

The P3 humanitarian and field-data capabilities add contextual public datasets and
operator-controlled, untrusted submissions without changing the authority of the
canonical disaster evidence pipeline.

## Trust boundaries

`UnverifiedFieldReport` is a separate domain type. It is never a trusted provider
observation and always retains `authority=unverified`, including after an import or
event association. Capture time, source-created time, receipt time, submitter
channel, point or polygon geometry, precision/uncertainty, media lineage, import
mapping, and review revision are retained.

Duplicate detection compares time, distance, and report type. Its output is only a
stable review candidate with `auto_merge=false`; frequency, duplication, an external
verified flag, or claimed model confidence cannot promote a report.

The human queue supports four decisions:

- reject;
- retain as unverified;
- associate the unverified report with an existing event; or
- admit a separate `OperatorObservation` under
  `operator-observation-admission.v1`.

The admission policy requires a named reviewer, rationale, existing event ID, and
explicit policy ID. The original report remains unverified. The resulting operator
observation is not an official observation and cannot replace source-backed evidence.

Analyst notes, tags, bookmarks, and runbook/checklist templates are exported with
`boundary=non_evidence_operator_state`. Checklists contain text references only and
cannot trigger autonomous actions.

Case notebooks extend the same non-evidence boundary. Operators can pin source
snapshot and analytical-run identifiers or record questions and conclusions for later
audit. Notebook entries cannot alter canonical state and are stored atomically with
the existing local operator workspace.

## Local storage and privacy

Reports, immutable review history, operator observations, notes, bookmarks, and
runbooks use atomically replaced local JSON stores. Stored files are mode `0600`.
Images are limited to JPEG and PNG, four per report, and a bounded byte size. Before
persistence, the API:

- rejects recognizable secrets, direct email addresses, and phone-number-like text;
- removes JPEG APP1/EXIF and PNG EXIF/text metadata;
- records original and stored SHA-256 checksums plus every transformation; and
- applies the configured retention expiry and deletes expired, corrupt-metadata, or
  orphaned media.

These controls are defensive filters, not a complete PII classifier. Operators must
still review text and visible image content before sharing.

## Humanitarian context

`GET /api/v1/humanitarian-context/{ISO3}` combines configured providers and returns
per-provider gaps rather than interpreting provider failure or an empty response as
no humanitarian need.

- HDX HAPI v2 supplies bounded baseline population, internal displacement, food
  security, and operational-presence context. Rows without an exact dataset ID,
  reference period, source URL, and license are omitted.
- IOM DTM v3 is optional and preserves administrative level, reporting time, round,
  dataset link, and license. DTM displacement is not attributed to the selected
  disaster unless a future source record explicitly supplies that relationship.
- Operational presence is coordination context. It is not endorsement and does not
  prove complete geographic or organizational coverage.
- ReliefWeb situation reports retain report/revision identity, themes,
  organizations, created/changed chronology, and a stale flag. Empty bounded searches
  emit a no-report gap that explicitly does not mean no impact.

## Imports and handoffs

`POST /api/v1/field-reports/imports` accepts reviewed KoboToolbox or ODK CSV/GeoJSON
with an explicit field mapping, reviewer attribution, and optional media keyed by
external record ID. Every row records the mapping and source record. External
verification is retained only as provenance and is never inherited.

The optional Ushahidi mapping accepts posts/categories/point locations into the same
unverified type. `GET /api/v1/field-reports/ushahidi-export` always emits
`unverified_by_disastermonitor`.

`POST /api/v1/mapping-workflows` produces a selected-AOI GeoJSON package and outbound
HOT Tasking Manager and MapSwipe links. It does not embed those systems or create a
task.

Evidence packages are deterministic ZIP archives with an incident snapshot, source
links, normalized data, findings, imagery manifests, software/policy versions, and a
SHA-256 manifest. Verification rejects unsafe, duplicate, undeclared, oversized,
schema-invalid, or checksum-invalid content. Verified imports are always marked
external and historical with `merge_into_live_state=false`.

## OSM context

Local OSM exposure analysis reports source update time, mapped feature count,
named-feature fraction, road density, and critical-facility density as proxies. An
empty result is not proof that no road or facility exists.

Critical-facility findings use only source-backed hazard geometry and versioned local
OSM assets. They report intersection or bounded proximity plus both source versions,
dataset age, calculation time, and a warning that proximity does not establish
damage, access, operation, or need.

`POST /api/v1/access-context/routes` is available only when a self-hosted OSRM URL and
explicit OSM data version are configured. It returns a route visualization estimate,
not an evacuation route or safety guarantee. Public routing hosts are rejected.

## Configuration

```dotenv
# HDX HAPI requires the operator's application identifier.
HDX_HAPI_APP_IDENTIFIER=

# IOM DTM is disabled unless both values are set.
IOM_DTM_API_URL=https://api.dtm.iom.int/v3/displacement
IOM_DTM_SUBSCRIPTION_KEY=

FIELD_REPORT_STORE_PATH=data/field-reports/reports.json
FIELD_MEDIA_ROOT=data/field-reports/media
FIELD_MEDIA_RETENTION_DAYS=30
FIELD_MEDIA_MAXIMUM_BYTES=100000000
OPERATOR_WORKSPACE_STORE_PATH=data/operator-workspace/workspace.json

# Must resolve to localhost/private network space and name the local extract version.
SELF_HOSTED_OSRM_URL=http://127.0.0.1:5000
SELF_HOSTED_OSRM_DATA_VERSION=geofabrik-YYYY-MM-DD
```

## Offline trust benchmark

The locked benchmark covers external verification manipulation, sensitive-content
misinformation, difficult approximate geolocation, and a 200-report coordinated
volume cluster. It asserts zero authority promotions, official-evidence overrides,
automatic merges, or invented exact locations. It is a boundary benchmark, not a
truth classifier.

```powershell
uv run --directory apps/api pytest -q tests/evaluation/test_field_report_trust_benchmark.py
```
