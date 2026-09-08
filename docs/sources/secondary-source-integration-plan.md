# Secondary-source research and integration plan

Research cutoff: 2026-09-08.

This review searched for global or consistently queryable secondary evidence across
the six configured hazards. A source clears the implementation bar only when it has a
documented and stable machine interface, usable rights, bounded provenance, actionable
freshness, and semantics that fit an existing application port without inventing facts.

## Decisions

| Candidate | Hazard coverage | Decision | Reason |
| --- | --- | --- | --- |
| Copernicus EMS Rapid Mapping | All six | Implemented | Public JSON API, exact supported categories, strong delivered `DEL`/`GRA` response products, and useful GDACS identifiers on many activations. It is event-conditioned map evidence, never discovery. |
| GDACS earthquake feed | Earthquake | Implemented | Public bounded GeoJSON feed adds operational resilience and GDACS/GLIDE identity. NEIC/USGS dependency is retained explicitly, so it is not counted as independent scientific corroboration. |
| NASA EONET expansion | Earthquake, flood, landslide, cyclone, volcano | Rejected | The 90-day live sample contained no earthquakes or landslides; flood records were GDACS, storms were mostly JTWC/NHC, and volcano records were Smithsonian. Those paths duplicate configured upstream families without adding stronger evidence. |
| IFRC GO field reports | All six | Deferred | Highly valuable structured humanitarian reporting, but raw responses can include contact and user fields that must not enter snapshots. IFRC's current Montandon STAC interface is explicitly staging, and its source analysis says the IFRC DREF source license is not stated. Prefer a production, non-PII projection with an explicit reuse basis. |
| EM-DAT | All six | Offline evaluation only | Validated historical impacts are useful for evaluation and calibration, but the public data updates weekly, requires registration and accepted terms, restricts redistribution, and is not request-time situation evidence. |
| GloFAS forecasts | Flood | Deferred | Valuable global forecast grids, but access requires an account/token and per-dataset terms acceptance. Turning daily ensemble discharge grids into event claims needs a separate forecast domain, climatology/threshold policy, and skill validation. Existing GFM supplies observed flood extent. |
| WMO RSMC/TCWC advisories | Tropical cyclone | Deferred | Authoritative regional advisories exist globally, but WMO currently links separate regional centres rather than exposing one stable normalized public event API. WIS 2.0 is the preferred future discovery path once centre/topic coverage can be proven. |
| ICAO/WMO VAAC advisories | Volcanic eruption | Deferred | Globally important ash advisories are exchanged as regional OPMET/IWXXM products. A unified public feed, centre reconciliation, and a dedicated ash-advisory domain are prerequisites; an ash advisory is not eruption or ground-impact evidence. |
| USGS ShakeMap/PAGER products | Earthquake | Planned | High-value situation detail already attached to configured USGS events. Add only after a provider-neutral hazard-map geometry model exists and estimated/modelled PAGER claims can remain separate from observed impacts. |
| GLIDE | All six | Identity only | Useful cross-system identifiers, but not a stronger evidence source. Continue preserving GLIDE IDs supplied by GDACS and other providers rather than adding duplicate discovery. |
| UNOSAT, International Charter, PDC | Multiple | Revisit on access change | Useful products exist, but no suitable credential-free, stable, documented global interface was available for this runtime. Charter/PDC access is controlled; no sufficiently stable official UNOSAT API contract was found. |

## Implemented architecture

Copernicus remains behind the existing situation-evidence port. There are six narrowly
scoped registrations backed by one category-driven adapter. This preserves one reason
to change for the HTTP/schema boundary while keeping registry and catalog capabilities
exact. The existing landslide source ID remains stable.

GDACS earthquake support remains behind the event-discovery port and reuses the
existing bounded pagination, country projection, network allowlist, snapshots, and
malformed-record isolation of the GDACS family. Only earthquake magnitude receives a
typed measurement; alert-model impacts remain excluded.

Both integrations use secondary authority and retain upstream identifiers. CEMS
normalizes a structured `gdacsId` into the same namespace as GDACS event observations,
allowing exact event association without name guessing. Fallback CEMS matching remains
bounded by country, three days, and 100 km. It is disabled for tropical cyclones because
the broader CEMS `Storm` category also includes non-cyclonic events.

## Next integration gates

1. Monitor the Montandon documentation for a production STAC endpoint. Before an IFRC
   adapter ships, verify license/reuse terms, collection freshness, per-field source
   lineage, and absence of personal data in the admitted projection. Add fixtures that
   prove data minimization before any live payload snapshot is enabled.
2. Introduce provider-neutral hazard-map and forecast concepts before ingesting USGS
   ShakeMap/PAGER, GloFAS, or VAAC geometry. Do not reuse cyclone-specific geometry or
   promote modelled exposure into observed impact facts.
3. Evaluate WIS 2.0 subscriptions for RSMC/TCWC and VAAC topics only after a live
   coverage audit can map all responsible centres, identifiers, update/retraction
   semantics, and rights.
4. Keep EM-DAT and displacement databases in offline evaluation pipelines unless their
   latency, access, and redistribution terms become suitable for request-time use.

## Verification plan

- Fixture tests: supported categories/types, pagination, schema failures, exact and
  fallback identity, product delivery, source authority, snapshots, and denied claims.
- Registry tests: all maintained countries and worldwide scope, exact role/tier/source
  metadata, configuration gaps, and no discovery/situation role leakage.
- Live checks: independently identify at least two recent upstream examples, exercise
  the adapters and running assistant with natural-language queries, compare selected
  identity and reported facts, and treat upstream absence/failure as a coverage gap.

Official references:

- `https://mapping.emergency.copernicus.eu/about/how-to-harvest-cems-mapping-data/emergency-response-data/`
- `https://www.gdacs.org/gdacsapi/swagger/index.html`
- `https://www.gdacs.org/Knowledge/models_eq.aspx`
- `https://eonet.gsfc.nasa.gov/docs/v3`
- `https://go-wiki.ifrc.org/en/go-api/Data_dictionary_field_report`
- `https://ifrcgo.org/monty-stac-extension/model/stac-api/`
- `https://doc.emdat.be/docs/data-accessibility/`
- `https://ewds.climate.copernicus.eu/datasets/cems-glofas-forecast`
- `https://community.wmo.int/site/knowledge-hub/programmes-and-initiatives/tropical-cyclone-programme-tcp/latest-advisories-rsmcs-and-tcwcs`
- `https://community.wmo.int/site/knowledge-hub/programmes-and-initiatives/wmo-information-system-wis/wis2-overview`
- `https://www.icao.int/sites/default/files/METP/Documents/Handbook-on-the-IAVW.Doc-9766.pdf`
