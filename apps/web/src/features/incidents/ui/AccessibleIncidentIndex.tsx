import {
  ActiveIncident,
  displayActiveIncidentCountry,
} from '@/features/incidents/model/activeIncidents';
import {
  activityStatusLabel,
  AUTHORITY_LABELS,
  disasterLabel,
  severityLabel,
} from '@/features/incidents/ui/incidentPresentation';

type AccessibleIncidentIndexProps = {
  incidents: ActiveIncident[];
  retrievedAt: string;
};

function formatDateTime(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

export function AccessibleIncidentIndex({
  incidents,
  retrievedAt,
}: AccessibleIncidentIndexProps) {
  return (
    <details className="incident-text-view">
      <summary>Text and print view</summary>
      <p>
        Hazard, activity, severity, authority, and source tier are written out so the
        distinctions do not depend on map color.
      </p>
      <div className="incident-text-table-wrap">
        <table aria-label="Text incident representation">
          <caption>Incident snapshot retrieved {formatDateTime(retrievedAt)}</caption>
          <thead>
            <tr>
              <th scope="col">Incident</th>
              <th scope="col">Hazard</th>
              <th scope="col">Activity</th>
              <th scope="col">Severity</th>
              <th scope="col">Authority</th>
              <th scope="col">Source tier</th>
              <th scope="col">Occurred</th>
            </tr>
          </thead>
          <tbody>
            {incidents.map((incident) => (
              <tr key={`${incident.disaster}:${incident.event_id}`}>
                <th scope="row">{displayActiveIncidentCountry(incident)}</th>
                <td>{disasterLabel(incident.disaster)}</td>
                <td>{activityStatusLabel(incident.activity_status)}</td>
                <td>{severityLabel(incident)}</td>
                <td>{AUTHORITY_LABELS[incident.source_authority]}</td>
                <td>
                  {incident.provider_tier === 'primary' ? 'Primary' : 'Secondary'}
                </td>
                <td>{formatDateTime(incident.event_time)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}
