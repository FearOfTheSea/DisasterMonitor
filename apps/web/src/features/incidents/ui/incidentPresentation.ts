import type {
  ActiveIncident,
  DisasterType,
  IncidentMapRecord,
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

export function relatedInvestigation(
  incident: Pick<IncidentMapRecord, 'disaster' | 'country'>,
): { label: string; question: string } {
  const hazard = `${disasterLabel(incident.disaster).toLowerCase()}s`;
  const scope = incident.country
    ? `${hazard} in ${incident.country.name}`
    : `worldwide ${hazard}`;
  return {
    label: `Ask about ${scope}`,
    question: incident.country
      ? `What are the latest ${scope}?`
      : `What are the latest ${hazard} worldwide?`,
  };
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
