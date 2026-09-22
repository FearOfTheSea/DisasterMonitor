import type {
  ActiveIncident,
  DisasterType,
  IncidentSourceAuthority,
} from '@/features/incidents/model/activeIncidents';

export const HAZARD_OPTIONS: { value: DisasterType; label: string }[] = [
  { value: 'earthquake', label: 'Earthquake' },
  { value: 'flood', label: 'Flood' },
  { value: 'wildfire', label: 'Wildfire' },
  { value: 'landslide', label: 'Landslide' },
  { value: 'drought', label: 'Drought' },
  { value: 'tropical_cyclone', label: 'Tropical cyclone' },
  { value: 'volcanic_eruption', label: 'Volcanic eruption' },
];

export const AUTHORITY_LABELS: Record<IncidentSourceAuthority, string> = {
  national_authority: 'National authority',
  scientific_authority: 'Scientific authority',
  humanitarian_aggregator: 'Humanitarian aggregator',
  secondary: 'Secondary authority',
};

export function disasterLabel(disaster: DisasterType): string {
  return HAZARD_OPTIONS.find((item) => item.value === disaster)?.label ?? disaster;
}

export function activityStatusLabel(status: ActiveIncident['activity_status']): string {
  switch (status) {
    case 'ongoing':
      return 'Ongoing';
    case 'ended':
      return 'Ended';
    default:
      return 'Activity unknown';
  }
}

export function severityLabel(incident: ActiveIncident): string {
  const severity = incident.measurements.find(
    (measurement) => measurement.kind === 'severity',
  );
  if (!severity) return 'Not reported';
  return severity.unit ? `${severity.value} ${severity.unit}` : String(severity.value);
}
