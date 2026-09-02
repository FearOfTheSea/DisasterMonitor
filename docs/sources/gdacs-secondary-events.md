# GDACS secondary event feeds

DisasterMonitor uses the official GDACS GeoJSON event-list API for bounded global and
named-country discovery.
It covers tropical cyclones (`TC`), floods (`FL`), wildfires (`WF`), and volcanic
eruptions (`VO`).

All four registrations have secondary tier and secondary source authority.

The API requires no key and returns at most 100 records per page.

DisasterMonitor follows pages in sequence until a short page exhausts the requested
date interval.
It stops at the internal limit of five pages or 500 raw records.

Snapshot each successful page with a page-specific credential-free request identity.

A later page failure keeps earlier valid records and adds a typed provider issue.

Reaching the limit emits `pagination_limit_reached`. It does not claim exhaustive
coverage.

GDACS asks API users to acknowledge “Global Disaster Alert and Coordination System,
GDACS.” Its terms describe products as modelled or semi-automatic outputs.
The outputs use information from scientific institutions and authoritative sources.

These products support potential international assistance. They are not local warnings
or guaranteed error-free facts.

The adapters retain stable GDACS event and episode IDs and any GLIDE identifier.
They also retain onset/end/update times, structured ISO-3 associations, source label,
event point, canonical detail link, and alert label.

The publisher string retains the per-record upstream label, such as GLOFAS, GWIS, NOAA,
or a VAAC.

Country projection requires structured GDACS country association and a usable point.
Classify the point against maintained country geometry. Do not treat it as an event
boundary.

## Floods (`FL`)

GDACS uses reviewed GloFAS/FloodList, ECHO, authoritative, and media-derived material
to create and update flood events.

The API often labels records `GLOFAS`.

CEMS GFM and GDACS FL are different products. GFM requires positive country-clipped
Sentinel-1 Observed Flood Extent pixels. GDACS is a curated flood-event record.

They overlap institutionally within the Copernicus/EC-JRC family. Their agreement is
not fully independent corroboration.

Do not promote GDACS centroids, impact thresholds, model severity, casualty, or
displacement fields. Retain event identity and the source-reported alert label only.

Assign GFM and GDACS observations to one physical flood only for the exact maintained
source pair.
Require source-backed points within 25 km and event times within 72 hours.

Keep other observations as separate candidates.

## Wildfires (`WF`)

GDACS wildfire events come from JRC’s Global Wildfire Information System (GWIS).
GWIS normally updates daily when imagery inputs are available.

Automatic admission normally requires at least 5,000 hectares.

Smaller events can enter after expert humanitarian-impact review. Homepage visibility
uses a stricter filter.

GWIS derives near-real-time burnt area from MODIS/VIIRS active-fire detections supplied
through NASA FIRMS.

GDACS WF is valid secondary event discovery. Its agreement with direct FIRMS
observations is not independent.

The event-list point is a centroid. It is not a perimeter, ignition, hotspot,
containment, impact, or warning claim.

Assign EONET and GDACS observations to one physical wildfire only for the exact
maintained source pair.
Require source-backed points within 25 km and event times within 72 hours.

Keep other observations as separate candidates.

## Volcanic eruptions (`VO`)

GDACS volcano status is based mainly on daily Volcanic Ash Advisories and Smithsonian
weekly reporting.

Orange or red humanitarian events can also enter manually.

The source label commonly names the responsible VAAC.

GDACS VO supports secondary discovery and corroboration. It depends on the
Smithsonian/USGS WVAR and VAA source families that it summarizes.

A point is a volcano location. It is not ash geometry or an exclusion zone.

Alert level is not a local warning, ash-concentration measurement, impact, casualty,
evacuation, or response claim.

Assign Smithsonian/USGS WVAR and GDACS observations to one physical eruption only for
the exact maintained source pair.
Require observation or event times within seven days and volcano points within 8 km.

Keep other observations as separate candidates.

These pairwise rules do not weaken the non-transitive clique requirement for multiple
observation identity.

## Testing and freshness

Freshness depends on provider and event type. Wildfire inputs are normally daily, VAAs
are daily, Smithsonian reports are weekly, and flood events change as reviewed
reporting arrives.

Missing GDACS records never prove absence.

Deterministic fixtures cover each event type, bounded query parameters, wrong-type
exclusion, malformed siblings, country projection, and upstream-label retention.
They also cover GLIDE/episode identity, network bounds, failure handling, authority,
and routing.

Tropical-cyclone-specific tests remain in their existing fixture suite.

References checked 2026-08-24:

- `https://www.gdacs.org/gdacsapi/swagger/index.html`
- `https://www.gdacs.org/Documents/2025/GDACS_API_quickstart_v2.pdf`
- `https://data.gdacs.org/About/termofuse.aspx`
- `https://www.gdacs.org/Knowledge/models_fl.aspx`
- `https://data.gdacs.org/Knowledge/models_wf.aspx`
- `https://www.gdacs.org/Knowledge/models_vo.aspx`
- `https://www.gdacs.org/documents/2025/GDACS_MHEWS_guide.pdf`
