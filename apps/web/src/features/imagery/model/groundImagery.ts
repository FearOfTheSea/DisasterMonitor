import type {
  GroundImageryArtifactResponse,
  GroundImageryReadinessResponse,
  GroundImageryRequestResponse,
  GroundImagerySelectionResponse,
  GroundImagerySensorStatusResponse,
  Sensor,
} from '@/shared/api/generated/assistant';

export type GroundImageryPanelRequest = GroundImageryRequestResponse;
export type GroundImageryPanelReadiness = GroundImageryReadinessResponse;

export const SENSOR_LABELS: Record<Sensor, string> = {
  'sentinel-1': 'Sentinel-1 radar',
  'sentinel-2': 'Sentinel-2 optical',
};

export const SENSOR_SHORT_LABELS: Record<Sensor, string> = {
  'sentinel-1': 'S1',
  'sentinel-2': 'S2',
};

const ROLE_LABELS: Record<string, string> = {
  pre_event_reference: 'Pre-event reference',
  first_useful_after_onset: 'First useful after onset',
  latest_useful: 'Latest useful view',
  earlier_reference: 'Earlier reference',
  recovery_checkpoint: 'Recovery checkpoint',
};

const STATE_LABELS: Record<string, string> = {
  ready: 'Ready',
  partial: 'Partial coverage',
  needs_region: 'Region needed',
  credentials_required: 'Credentials required',
  artifact_pipeline_unavailable: 'Artifact pipeline unavailable',
  disabled: 'Disabled',
  selected: 'Selected',
  no_acquisition: 'No acquisition',
  no_recent_observation: 'No recent observation',
  obscured: 'Obscured or uncertain',
  partial_coverage: 'Partial coverage',
  not_renderable_yet: 'Catalogued; rendering pending',
  no_comparable_baseline: 'No comparable baseline',
  onset_unknown: 'Onset unknown',
};

export function labelImageryRole(role: string): string {
  return ROLE_LABELS[role] ?? role.replaceAll('_', ' ');
}

export function labelImageryState(state: string): string {
  return STATE_LABELS[state] ?? state.replaceAll('_', ' ');
}

export function formatImageryTime(value: string | null | undefined): string {
  if (!value) return 'Not available';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    timeZoneName: 'short',
  }).format(date);
}

export function formatFraction(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return 'Not assessed';
  }
  return `${Math.round(value * 100)}%`;
}

export function sensorStatus(
  request: GroundImageryPanelRequest,
  sensor: Sensor,
): GroundImagerySensorStatusResponse | undefined {
  return request.sensors.find((item) => item.sensor === sensor);
}

export function artifactForSelection(
  artifacts: GroundImageryArtifactResponse[] | undefined,
  selectionId: string,
): GroundImageryArtifactResponse | undefined {
  return artifacts?.find((artifact) => artifact.selection_id === selectionId);
}

export function statusClass(state: string): string {
  if (state === 'ready' || state === 'selected') return 'is-positive';
  if (
    state === 'partial' ||
    state === 'partial_coverage' ||
    state === 'needs_region' ||
    state === 'credentials_required'
  ) {
    return 'is-warning';
  }
  if (state === 'disabled' || state === 'artifact_pipeline_unavailable') {
    return 'is-negative';
  }
  return 'is-neutral';
}

export function roleOutcomes(
  status: GroundImagerySensorStatusResponse | undefined,
): GroundImagerySelectionResponse[] {
  return status?.selections ?? [];
}
