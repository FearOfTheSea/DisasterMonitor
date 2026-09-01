export type MapLayerId =
  | 'active-incidents'
  | 'satellite-imagery'
  | 'cop-evidence'
  | 'cyclone-supplemental'
  | 'compound-correlations';

export type MapLayerCategory =
  'incidents' | 'imagery' | 'evidence' | 'forecast' | 'context';

export type MapLayerDefinition = {
  id: MapLayerId;
  label: string;
  category: MapLayerCategory;
  defaultVisible: boolean;
  purpose: string;
  sourceDescription: string;
  freshnessSemantics: string;
  authorityDescription: string;
  attribution?: string;
  limitations: readonly string[];
};

export const MAP_LAYER_REGISTRY = [
  {
    id: 'active-incidents',
    label: 'Active incidents',
    category: 'incidents',
    defaultVisible: true,
    purpose: 'Displays source-backed incident point, track, and area geometry.',
    sourceDescription:
      'Configured DisasterMonitor event-discovery providers returned through the Active Incidents transport.',
    freshnessSemantics:
      'The snapshot retrieval time describes when DisasterMonitor completed the bounded request. Each record retains its own published, updated, and retrieved timestamps.',
    authorityDescription:
      'Each incident retains its provider tier and source-authority classification. Coverage state is reported separately for every hazard.',
    limitations: [
      'Displayed records are bounded by configured providers and the selected display window; they do not establish complete global surveillance.',
      'A successful empty result does not prove that no disaster occurred.',
    ],
  },
  {
    id: 'satellite-imagery',
    label: 'Satellite imagery',
    category: 'imagery',
    defaultVisible: false,
    purpose: 'Adds one selected satellite raster beneath source-backed vector layers.',
    sourceDescription:
      'NASA GIBS public imagery or a configured Copernicus Sentinel Hub or Planet mosaic served through DisasterMonitor.',
    freshnessSemantics:
      'The control selects a requested observation date or UTC time. The client does not claim that imagery exists for that request.',
    authorityDescription:
      'Imagery is visual context from the named provider, not incident confirmation, a warning, or an impact assessment.',
    attribution:
      'Provider-specific attribution is shown for the selected imagery source.',
    limitations: [
      'Imagery is not live.',
      'Cloud, revisit, processing, and configured-mosaic limits may affect what is visible.',
    ],
  },
  {
    id: 'cop-evidence',
    label: 'COP evidence',
    category: 'evidence',
    defaultVisible: true,
    purpose:
      'Displays retained Common Operational Picture geometry with source and analytical authority kept distinct.',
    sourceDescription:
      'The current assistant report Common Operational Picture, including feature-level attribution and retained source asset identifiers.',
    freshnessSemantics:
      'Layer and feature status, uncertainty, created time, and updated time come from the returned Common Operational Picture.',
    authorityDescription:
      'Official-source, source-supplied, and analytical generated features use distinct textual labels and line patterns.',
    limitations: [
      'Analytical geometry remains AI-generated analysis and cannot create verified facts or expand source authority.',
      'Status and uncertainty mean only what the returned Common Operational Picture states.',
    ],
  },
  {
    id: 'cyclone-supplemental',
    label: 'Cyclone supplemental geometry',
    category: 'forecast',
    defaultVisible: true,
    purpose:
      'Displays retained provisional track, forecast track, uncertainty, and wind-radii geometry when supplied for the selected cyclone.',
    sourceDescription:
      'Source-backed NOAA IBTrACS provisional context and NOAA NHC/CPHC advisory products attached to the selected event.',
    freshnessSemantics:
      'Issued, valid-from, and valid-to timestamps retain the meaning reported by each supplemental layer source.',
    authorityDescription:
      'Provisional observations and forecasts remain separate semantic roles with source attribution and reconciliation details.',
    limitations: [
      'Forecast and uncertainty geometry are not observed storm footprints.',
      'These layers are not wind fields, public warnings, impact forecasts, or complete global forecast coverage.',
    ],
  },
  {
    id: 'compound-correlations',
    label: 'Compound-hazard correlations',
    category: 'context',
    defaultVisible: true,
    purpose:
      'Controls visibility of rule-bounded descriptive correlations in operator findings without drawing inferred connector geometry.',
    sourceDescription:
      'CompoundHazardCorrelation records returned with the Active Incidents snapshot, retaining the contributing source identifiers.',
    freshnessSemantics:
      'Correlation visibility follows the selected display window only when both retained incident records have timestamps inside that window.',
    authorityDescription:
      'A correlation is a deterministic spatiotemporal association between distinct records, not a merged incident or causal claim.',
    limitations: [
      'Spatial and temporal proximity does not establish causation.',
      'No inferred line, footprint, risk score, or forecast is created for this layer.',
    ],
  },
] as const satisfies readonly MapLayerDefinition[];

const DEFINITIONS_BY_ID = new Map(
  MAP_LAYER_REGISTRY.map((definition) => [definition.id, definition]),
);

export function mapLayerDefinition(id: MapLayerId): MapLayerDefinition {
  return DEFINITIONS_BY_ID.get(id) as MapLayerDefinition;
}
