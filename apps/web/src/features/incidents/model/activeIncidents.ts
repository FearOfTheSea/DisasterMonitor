export type DisasterType =
  | 'earthquake'
  | 'flood'
  | 'wildfire'
  | 'landslide'
  | 'tropical_cyclone'
  | 'volcanic_eruption';

export type IncidentCoverageState =
  'events_found' | 'no_matching_records' | 'degraded' | 'unavailable';

export type IncidentSourceAuthority =
  | 'national_authority'
  | 'scientific_authority'
  | 'humanitarian_aggregator'
  | 'secondary';

export type IncidentSource = {
  source_id: string;
  publisher: string;
  title: string;
  canonical_url: string;
  published_at: string | null;
  updated_at: string | null;
  retrieved_at: string;
  snapshot_id: string | null;
};

export type IncidentCoordinate = {
  latitude: number;
  longitude: number;
};

export type IncidentGeometry = {
  kind: 'point' | 'area' | 'track' | 'descriptive';
  coordinates: IncidentCoordinate[];
  description: string | null;
  source_id: string;
  estimated: boolean;
};

export type IncidentMeasurement = {
  kind:
    | 'magnitude'
    | 'intensity'
    | 'depth'
    | 'provider_significance'
    | 'confidence'
    | 'fire_radiative_power'
    | 'severity';
  value: number | string;
  unit: string | null;
  source_id: string;
};

export type ActiveIncident = {
  event_id: string;
  disaster: DisasterType;
  location: string;
  event_time: string;
  geometry: IncidentGeometry | null;
  measurements: IncidentMeasurement[];
  provider_ids: string[];
  provider_tier: 'primary' | 'secondary';
  source_authority: IncidentSourceAuthority;
  source: IncidentSource;
};

export type DisasterIncidentCoverage = {
  disaster: DisasterType;
  state: IncidentCoverageState;
  incident_count: number;
  providers: string[];
  detail: string;
};

export type ActiveIncidentsSnapshot = {
  retrieved_at: string;
  incidents: ActiveIncident[];
  coverage: DisasterIncidentCoverage[];
  warnings: string[];
};
