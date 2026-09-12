import {
  countryAssociationLabel,
  DisasterType,
  displayActiveIncidentCountry,
  displayActiveIncidentContext,
  IncidentMapRecord,
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
  onGroundView,
}: {
  incident?: IncidentMapRecord;
  onAsk: () => void;
  onGroundView?: () => void;
}) {
  if (!incident) return null;
  const sourceCount = Math.max(1, incident.provider_ids.length);
  const context = displayActiveIncidentContext(incident);

  return (
    <article
      className={`selected-incident-summary selected-incident-${incident.disaster}`}
    >
      <div className="selected-incident-icon" aria-hidden="true">
        <DisasterIcon disaster={incident.disaster} />
      </div>
      <div className="selected-incident-copy">
        <span>{DISASTER_LABELS[incident.disaster]}</span>
        <h3>{displayActiveIncidentCountry(incident)}</h3>
        {context ? <small>{context}</small> : null}
        <p>
          {relativeEventTime(incident.event_time)} · {sourceCount}{' '}
          {sourceCount === 1 ? 'trusted source' : 'trusted sources'}
        </p>
        <div className="selected-incident-actions">
          <button type="button" onClick={onAsk}>
            View what we know
          </button>
          {onGroundView ? (
            <button
              type="button"
              className="selected-incident-ground-button"
              onClick={onGroundView}
            >
              Open Ground view
            </button>
          ) : null}
        </div>
      </div>
      <details>
        <summary>Technical details</summary>
        <dl>
          <div>
            <dt>Event ID</dt>
            <dd>{incident.event_id}</dd>
          </div>
          <div>
            <dt>Country association</dt>
            <dd>{countryAssociationLabel(incident)}</dd>
          </div>
          <div>
            <dt>Source location</dt>
            <dd>{incident.location}</dd>
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
