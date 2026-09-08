# Copernicus EMS Rapid Mapping evidence

Copernicus Emergency Management Service (CEMS) Rapid Mapping is secondary map
evidence for an already selected disaster event. It is not an event-discovery provider.

DisasterMonitor uses the credential-free public Rapid Mapping JSON APIs for all six
configured hazards:

| Disaster | API query | Required response category | Source ID |
| --- | --- | --- | --- |
| Earthquake | `earthquake` | `Earthquake` | `copernicus-rapid-mapping-earthquakes` |
| Flood | `flood` | `Flood` | `copernicus-rapid-mapping-floods` |
| Wildfire | `wildfire` | `Wildfire` | `copernicus-rapid-mapping-wildfires` |
| Landslide | `mass` | `Mass movement` | `copernicus-rapid-mapping-landslides` |
| Tropical cyclone | `storm` | `Storm` | `copernicus-rapid-mapping-tropical-cyclones` |
| Volcanic eruption | `volcanic` | `Volcanic activity` | `copernicus-rapid-mapping-volcanic-eruptions` |

The original landslide source ID remains unchanged. Each additional hazard has its own
stable source ID and executable registration so catalog capability and runtime routing
cannot drift into a broad, ambiguous provider declaration.

## Admission and correlation

An activation request alone never proves that a disaster occurred. A candidate must:

- use an `EMSR` Rapid Mapping code;
- match the configured CEMS category exactly;
- name the selected country for a country-scoped request;
- advertise at least one product; and
- supply an event time and valid WGS84 centroid.

When CEMS publishes a `gdacsId`, DisasterMonitor normalizes identifiers such as
`FL1104081` to `gdacs:fl:1104081`. An exact identifier shared with the selected physical
event is a matched association. This path remains subject to hazard and country checks,
but it does not require a moving or broad event to remain within the fallback
time-and-centroid bounds.

Without a shared identifier, the activation time must be within three days and its
centroid within 100 km of the selected source-backed event point. That conservative
geotemporal path retains `possible` correlation metadata. At most five ranked
candidates receive a detail request, with exact-ID candidates ranked first.

The CEMS `Storm` category also contains non-cyclonic storms. Tropical-cyclone evidence
therefore requires an exact shared `TC` GDACS identifier; the fallback geotemporal path
is disabled for that hazard.

The detail response must contain a feasible, delivered delineation (`DEL`) or grading
(`GRA`) product with a published map. Reference (`REF`) products and activation
metadata alone do not qualify. Risk and Recovery (`EMSN`) activations are excluded.

Qualifying reports preserve the EMSR code, normalized GDACS ID when present, event and
activation times, delivered product types, activation title, source link, and immutable
snapshot provenance. Product statistics are not imported as total extent, damage,
casualties, warnings, response status, or national totals. Areas of Interest are
requested mapping areas and need not cover the complete event. A storm activation is
not a forecast track, cone, or wind field; a volcanic activation is not an ash advisory
or ash-concentration product.

The service runs on demand. An authorised user must request an activation, so missing
results are a coverage gap rather than evidence that no event occurred.

## Live verification

The public activation API was checked on 2026-09-08. It returned records in every
configured category: 8 earthquakes, 88 floods, more than 100 wildfires, 3 mass
movements, 25 storms, and 1 volcanic-activity activation. Live detail requests
qualified EMSR884 (earthquake in Venezuela, `GRA`), EMSR927 (flood in Nepal, `GRA`),
EMSR929 (wildfire in Greece, `DEL`), EMSR751 (mass movement in Italy, `GRA`), EMSR872
(Tropical Cyclone Sinlaku, `GRA`), and EMSR912 (volcanic activity in Guatemala, `DEL`).

Payload snapshots use rights identifier `copernicus-data-legal-notice`.

Deterministic tests cover all six category mappings, stable source IDs, shared GDACS
identity, fallback country/time/distance correlation, EMSR-only admission, delivered
product qualification, risk-assessment exclusion, missing geometry, snapshots,
routing, and source policy.

References checked 2026-09-08:

- `https://mapping.emergency.copernicus.eu/about/how-to-harvest-cems-mapping-data/emergency-response-data/`
- `https://mapping.emergency.copernicus.eu/about/rapid-mapping-portfolio/`
- `https://rapidmapping.emergency.copernicus.eu/backend/dashboard-api/public-activations-info/`
- `https://rapidmapping.emergency.copernicus.eu/backend/dashboard-api/public-activations/?code=EMSR916`
