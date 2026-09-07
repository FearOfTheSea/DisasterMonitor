import {
  ActiveIncident,
  DisasterType,
  displayActiveIncidentLocation,
} from '@/features/incidents/model/activeIncidents';
import { DisasterIcon } from '@/features/incidents/ui/DisasterIcon';

const DISASTER_LABELS: Record<DisasterType, string> = {
  earthquake: 'Earthquake',
  flood: 'Flood',
  wildfire: 'Wildfire',
  landslide: 'Landslide',
  tropical_cyclone: 'Tropical cyclone',
  volcanic_eruption: 'Volcanic eruption',
};

function relativeEventTime(value: string): string {
  const eventTime = new Date(value).getTime();
  if (Number.isNaN(eventTime)) return value;
  const hours = Math.max(0, Math.round((Date.now() - eventTime) / 3_600_000));
  if (hours < 1) return 'Reported recently';
  if (hours < 24) return `Reported ${hours} ${hours === 1 ? 'hour' : 'hours'} ago`;
  const days = Math.round(hours / 24);
  return `Reported ${days} ${days === 1 ? 'day' : 'days'} ago`;
}

export function SelectedIncidentSummary({
  incident,
  onAsk,
}: {
  incident?: ActiveIncident;
  onAsk: () => void;
}) {
  if (!incident) return null;
  const sourceCount = Math.max(1, incident.provider_ids.length);

  return (
    <article
      className={`selected-incident-summary selected-incident-${incident.disaster}`}
    >
      <div className="selected-incident-icon" aria-hidden="true">
        <DisasterIcon disaster={incident.disaster} />
      </div>
      <div className="selected-incident-copy">
        <span>{DISASTER_LABELS[incident.disaster]}</span>
        <h3>{displayActiveIncidentLocation(incident)}</h3>
        <p>
          {relativeEventTime(incident.event_time)} · {sourceCount}{' '}
          {sourceCount === 1 ? 'trusted source' : 'trusted sources'}
        </p>
        <button type="button" onClick={onAsk}>
          View what we know
        </button>
      </div>
      <details>
        <summary>Technical details</summary>
        <dl>
          <div>
            <dt>Event ID</dt>
            <dd>{incident.event_id}</dd>
          </div>
          <div>
            <dt>Publisher</dt>
            <dd>{incident.source.publisher}</dd>
          </div>
        </dl>
        <a href={incident.source.canonical_url} target="_blank" rel="noreferrer">
          Open original source
        </a>
      </details>
    </article>
  );
}
