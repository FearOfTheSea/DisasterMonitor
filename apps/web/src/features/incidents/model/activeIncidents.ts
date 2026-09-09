export type DisasterType =
  | 'earthquake'
  | 'flood'
  | 'wildfire'
  | 'landslide'
  | 'tropical_cyclone'
  | 'volcanic_eruption';

export type IncidentCoverageState =
  'events_found' | 'no_matching_records' | 'degraded' | 'unavailable';

export type ObservationKind = 'physical_event' | 'acquisition';

export type IncidentActivityStatus = 'ongoing' | 'ended' | 'unknown';

export type IncidentVerificationStatus =
  'provisional_news_detected' | 'source_backed' | 'rejected';

export type IncidentDetectionTimeline = {
  news_break_at: string | null;
  first_observed_at: string | null;
  candidate_created_at: string | null;
  verified_at: string | null;
  monitor_visible_at: string | null;
  assistant_ready_at: string | null;
};

export type IncidentView = 'recent' | 'ongoing' | 'recently_updated' | 'historical';

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

export type IncidentCountryAssociationBasis =
  'coordinate_polygon' | 'source_mention' | 'named_region' | 'nearby_boundary';

export type IncidentCountry = {
  code: string;
  name: string;
  association_basis: IncidentCountryAssociationBasis;
  distance_km: number | null;
};

export type ActiveIncident = {
  event_id: string;
  physical_event_id?: string | null;
  disaster: DisasterType;
  country: IncidentCountry | null;
  location: string;
  event_time: string;
  geometry: IncidentGeometry | null;
  measurements: IncidentMeasurement[];
  provider_ids: string[];
  lineage_ids?: string[];
  provider_tier: 'primary' | 'secondary';
  source_authority: IncidentSourceAuthority;
  source: IncidentSource;
  evidence_sources?: IncidentSource[];
  observation_kind?: ObservationKind;
  activity_status?: IncidentActivityStatus;
  verification_status?: IncidentVerificationStatus;
  detection?: IncidentDetectionTimeline;
};

export type IncidentMapRecord = Omit<ActiveIncident, 'country'> & {
  country?: IncidentCountry | null;
};

export function displayActiveIncidentCountry(incident: IncidentMapRecord): string {
  return incident.country?.name ?? incident.location;
}

export function countryAssociationLabel(incident: IncidentMapRecord): string {
  if (!incident.country) return 'Country association unavailable';
  switch (incident.country.association_basis) {
    case 'coordinate_polygon':
      return 'Coordinate within mapped country or territory';
    case 'source_mention':
      return 'Country or territory named by source';
    case 'named_region':
      return 'Verified named-region association';
    case 'nearby_boundary':
      return incident.country.distance_km === null
        ? 'Near a mapped country or territory boundary'
        : `${incident.country.distance_km.toFixed(1)} km from mapped boundary`;
  }
}

export function displayActiveIncidentContext(
  incident: IncidentMapRecord,
): string | null {
  const country = displayActiveIncidentCountry(incident);
  if (incident.location === country) return null;
  if (
    incident.source.source_id === 'cems-gfm-floods' &&
    incident.location.startsWith('CEMS GFM acquisition ')
  ) {
    return countryAssociationLabel(incident);
  }
  return incident.location;
}

export type CompoundHazardCorrelation = Omit<
  CompoundHazardCorrelationResponse,
  'source_ids'
> & {
  source_ids: string[];
};

export type DisasterIncidentCoverage = {
  disaster: DisasterType;
  state: IncidentCoverageState;
  incident_count: number;
  providers: string[];
  detail: string;
  scan_complete?: boolean;
  records_seen?: number;
  truncated?: boolean;
};

export type ActiveIncidentsSnapshot = {
  retrieved_at: string;
  incidents: ActiveIncident[];
  coverage: DisasterIncidentCoverage[];
  warnings: string[];
  observations?: ActiveIncident[];
  correlations?: CompoundHazardCorrelation[];
  snapshot_version?: string | null;
  next_cursor?: string | null;
  has_more?: boolean;
  total_incident_count?: number | null;
};
import type { CompoundHazardCorrelationResponse } from '@/shared/api/generated/assistant';
