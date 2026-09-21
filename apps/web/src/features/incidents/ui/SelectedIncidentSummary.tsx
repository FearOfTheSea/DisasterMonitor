import { EventBrief } from '@/features/event-brief/public';
import {
  DisasterType,
  displayActiveIncidentCountry,
  displayActiveIncidentContext,
  IncidentMapRecord,
} from '@/features/incidents/model/activeIncidents';
import { DisasterIcon } from '@/features/incidents/ui/DisasterIcon';
import type { WeatherAlertsSnapshot } from '@/features/weather/public';

const DISASTER_LABELS: Record<DisasterType, string> = {
  earthquake: 'Earthquake',
  flood: 'Flood',
  wildfire: 'Wildfire',
  landslide: 'Landslide',
  drought: 'Drought',
  tropical_cyclone: 'Tropical cyclone',
  volcanic_eruption: 'Volcanic eruption',
};

function relativeEventTime(value: string, reference: string): string {
  const eventTime = new Date(value).getTime();
  const referenceTime = new Date(reference).getTime();
  if (Number.isNaN(eventTime) || Number.isNaN(referenceTime)) return value;
  const minutes = Math.max(0, Math.round((referenceTime - eventTime) / 60_000));
  if (minutes < 5) return 'Reported recently';
  if (minutes < 60) return `Reported ${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `Reported ${hours} ${hours === 1 ? 'hour' : 'hours'} ago`;
  const days = Math.round(hours / 24);
  return `Reported ${days} ${days === 1 ? 'day' : 'days'} ago`;
}

export function SelectedIncidentSummary({
  incident,
  onAsk,
  onGroundView,
  onDismiss,
  snapshotRetrievedAt,
  warnings,
}: {
  incident?: IncidentMapRecord;
  onAsk: () => void;
  onGroundView?: () => void;
  onDismiss?: () => void;
  snapshotRetrievedAt: string;
  warnings?: WeatherAlertsSnapshot;
}) {
  if (!incident) return null;
  const sourceCount = Math.max(1, incident.provider_ids.length);
  const context = displayActiveIncidentContext(incident);

  return (
    <article
      className={`selected-incident-summary selected-incident-${incident.disaster}`}
    >
      {onDismiss ? (
        <button
          type="button"
          className="selected-incident-dismiss"
          aria-label="Clear selected event"
          onClick={onDismiss}
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="m6 6 12 12M18 6 6 18" />
          </svg>
        </button>
      ) : null}
      <div className="selected-incident-icon" aria-hidden="true">
        <DisasterIcon disaster={incident.disaster} />
      </div>
      <div className="selected-incident-copy">
        <span>{DISASTER_LABELS[incident.disaster]}</span>
        <h3>{displayActiveIncidentCountry(incident)}</h3>
        {context ? <small>{context}</small> : null}
        <p>
          {relativeEventTime(incident.event_time, snapshotRetrievedAt)} · {sourceCount}{' '}
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
        <summary>Event brief</summary>
        <EventBrief
          incident={incident}
          warnings={warnings}
          onGroundView={onGroundView ?? (() => undefined)}
        />
      </details>
    </article>
  );
}
