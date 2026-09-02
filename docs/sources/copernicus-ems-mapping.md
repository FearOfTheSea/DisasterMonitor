# Copernicus EMS Rapid Mapping landslide evidence

Copernicus Emergency Management Service (CEMS) Rapid Mapping is secondary mapping
evidence for a selected landslide.

It is not an event-discovery provider. DisasterMonitor uses the public Rapid Mapping
JSON APIs without credentials.

An activation request alone never proves that a landslide occurred.

The activation-list request is limited to 100 `Mass movement` records.

A candidate must meet every condition below:

- use an `EMSR` Rapid Mapping code;
- name the selected country for a country-scoped request;
- report an event time within three days of the selected event;
- place its activation centroid within 100 km of the selected source-backed point; and
- advertise at least one product.

At most five ranked candidates receive a detail request.

The detail must contain a feasible, delivered delineation (`DEL`) or grading (`GRA`)
product with a published map.

Reference (`REF`) products and activation metadata alone do not qualify.

Qualifying output is one `possible`-correlation situation report.

It preserves the EMSR code, event and activation times, product types, activation title,
centroid-match context, source link, and snapshot.

It does not import product statistics as total event extent, damage, casualties,
warnings, response status, or national totals.

Areas of Interest are requested mapping areas. They need not cover the complete event.

Risk and Recovery (`EMSN`) activations are excluded.

Those products can describe preparedness, susceptibility, risk, or recovery instead of
confirmed occurrence.

CEMS Rapid Mapping and NASA COOLR expose no shared stable event ID in the integrated
interfaces.

Temporal and spatial agreement therefore does not become an exact identity claim.

The service runs on demand. An authorised user must request an activation.

Many real landslides will have no CEMS product.

During the 2026-08-24 live check, the category-filtered Rapid Mapping API exposed three
historical mass-movement activations.

EMSR751, “Mass movement in Campania Region, Italy,” reported event time 2024-08-27 and
a feasible final `GRA` product.

The current active window had no recent qualifying mass-movement activation.

This absence is a coverage gap. It is not evidence of no landslide.

Payload snapshots use rights identifier `copernicus-data-legal-notice`.

Deterministic tests cover response-list and detail schemas, EMSR-only admission,
product delivery, country/time/distance correlation, and risk-assessment exclusion.
They also cover missing geometry, wrong-disaster exclusion, snapshots, routing, and
source policy.

References checked 2026-08-24:

- `https://mapping.emergency.copernicus.eu/about/how-to-harvest-cems-mapping-data/emergency-response-data/`
- `https://mapping.emergency.copernicus.eu/about/rapid-mapping-manual/product-overview/`
- `https://mapping.emergency.copernicus.eu/about/rapid-mapping-manual/product-overview/what-is-delivered-in-a-product/`
- `https://rapidmapping.emergency.copernicus.eu/backend/dashboard-api/public-activations-info/`
- `https://rapidmapping.emergency.copernicus.eu/backend/dashboard-api/public-activations/?code=EMSR751`
