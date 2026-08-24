# GDACS secondary event feeds

DisasterMonitor uses the official GDACS GeoJSON event-list API for bounded global and
named-country discovery of tropical cyclones (`TC`), floods (`FL`), wildfires (`WF`),
and volcanic eruptions (`VO`). All four registrations are secondary tier and secondary
source authority. The API requires no key and returns at most 100 records per page.
DisasterMonitor follows pages sequentially until a short page exhausts the requested
date interval or the internal ceiling of five pages/500 raw records is reached. Every
successful page is snapshotted with a page-specific credential-free request identity.
A later page failure retains earlier valid records with a typed provider issue; reaching
the ceiling emits `pagination_limit_reached` rather than claiming exhaustive coverage.
GDACS asks API users to acknowledge “Global Disaster Alert and Coordination System,
GDACS.” Its terms describe products as modelled or semi-automatic outputs built from
scientific institutions and authoritative information for potential international
assistance; they are not local warnings or guaranteed error-free facts.

The adapters retain the stable GDACS event and episode IDs, any GLIDE identifier,
onset/end/update times, structured ISO-3 associations, source label, event point,
canonical detail link, and alert label. The publisher string retains the per-record
upstream label (for example GLOFAS, GWIS, NOAA, or a VAAC). Country projection requires
structured GDACS country association and a usable point; the point is classified
against maintained country geometry rather than treated as an event boundary.

## Floods (`FL`)

GDACS currently uses reviewed GloFAS/FloodList, ECHO, authoritative, and media-derived
material to create and update flood events. The API often labels records `GLOFAS`.
CEMS GFM and GDACS FL are different products: GFM requires positive country-clipped
Sentinel-1 Observed Flood Extent pixels, while GDACS is a curated flood-event record.
They nevertheless overlap institutionally within the Copernicus/EC-JRC family, and
their agreement is not counted as fully independent corroboration. GDACS centroids,
impact thresholds, model severity, casualty, and displacement fields are not promoted;
only event identity plus source-reported alert label are retained.

GFM and GDACS observations are assigned to one physical flood only for the exact
maintained source pair when both have source-backed points within 25 km and event times
within 72 hours. Otherwise they remain separate candidates.

## Wildfires (`WF`)

GDACS wildfire events are produced from JRC’s Global Wildfire Information System
(GWIS), normally updated daily when imagery inputs are available. Automatic admission
normally requires at least 5,000 hectares; smaller events can be inserted after expert
humanitarian-impact review, while homepage visibility has a stricter filter. GWIS
derives near-real-time burnt area from MODIS/VIIRS active-fire detections supplied
through NASA FIRMS. GDACS WF is therefore valid secondary event discovery, but its
agreement with direct FIRMS observations is not independent. The event-list point is a
centroid, not a perimeter, ignition, hotspot, containment, impact, or warning claim.

EONET and GDACS observations are assigned to one physical wildfire only for the exact
maintained source pair when both have source-backed points within 25 km and event times
within 72 hours. Otherwise they remain separate candidates.

## Volcanic eruptions (`VO`)

GDACS volcano status is based mainly on daily Volcanic Ash Advisories and Smithsonian
weekly reporting, with orange/red humanitarian events also introduced manually. The
record’s source label commonly names the responsible VAAC. This makes GDACS VO useful
secondary discovery/corroboration but dependent on the same Smithsonian/USGS WVAR and
VAA source families it summarizes. A point is a volcano location, not ash geometry or
an exclusion zone. Alert level is not a local warning, ash-concentration measurement,
impact, casualty, evacuation, or response claim.

Smithsonian/USGS WVAR and GDACS observations are assigned to one physical eruption only
for the exact maintained source pair when their source-backed observation/event times
are within seven days and their volcano points are within 8 km. Otherwise they remain
separate candidates. These pairwise rules do not weaken the non-transitive clique
requirement for multi-observation identity.

## Testing and freshness

Freshness is provider and event-type dependent: wildfire inputs are normally daily,
VAAs daily, Smithsonian reports weekly, and flood events change as reviewed reporting
arrives. Missing GDACS records never prove absence. Deterministic fixtures cover each
event type, bounded query parameters, wrong-type exclusion, malformed siblings,
country projection, upstream label retention, GLIDE/episode identity, network bounds,
failure handling, authority, and routing. Tropical-cyclone-specific tests remain in
their existing fixture suite.

References checked 2026-08-24:

- `https://www.gdacs.org/gdacsapi/swagger/index.html`
- `https://www.gdacs.org/Documents/2025/GDACS_API_quickstart_v2.pdf`
- `https://data.gdacs.org/About/termofuse.aspx`
- `https://www.gdacs.org/Knowledge/models_fl.aspx`
- `https://data.gdacs.org/Knowledge/models_wf.aspx`
- `https://www.gdacs.org/Knowledge/models_vo.aspx`
- `https://www.gdacs.org/documents/2025/GDACS_MHEWS_guide.pdf`
