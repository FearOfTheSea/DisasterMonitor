import type {
  ActiveIncident,
  DisasterType,
  IncidentGeometry,
} from '@/features/incidents/model/activeIncidents';

export type RenderableIncidentGeometry = IncidentGeometry & {
  kind: 'point' | 'area' | 'track';
};

export type ActiveIncidentMapFeature = {
  incidentId: string;
  disaster: DisasterType;
  geometry: RenderableIncidentGeometry;
};

function isRenderableGeometry(
  geometry: IncidentGeometry | null,
): geometry is RenderableIncidentGeometry {
  if (!geometry || geometry.kind === 'descriptive') return false;
  if (geometry.kind === 'point') return geometry.coordinates.length === 1;
  if (geometry.kind === 'track') return geometry.coordinates.length >= 2;
  return geometry.coordinates.length >= 3;
}

export function activeIncidentMapFeatures(
  incidents: readonly ActiveIncident[],
): ActiveIncidentMapFeature[] {
  return incidents.flatMap((incident) =>
    isRenderableGeometry(incident.geometry)
      ? [
          {
            incidentId: incident.event_id,
            disaster: incident.disaster,
            geometry: incident.geometry,
          },
        ]
      : [],
  );
}
