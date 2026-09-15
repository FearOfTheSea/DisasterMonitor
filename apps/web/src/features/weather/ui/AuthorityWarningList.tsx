import { useMemo, useState } from 'react';

import type {
  WeatherAlert,
  WeatherAlertCertainty,
  WeatherAlertSeverity,
  WeatherAlertUrgency,
} from '@/features/weather/model/weatherAlert';

type FilterValue = 'all' | string;

export function AuthorityWarningList({ alerts }: { alerts: readonly WeatherAlert[] }) {
  const [source, setSource] = useState<FilterValue>('all');
  const [eventType, setEventType] = useState('');
  const [severity, setSeverity] = useState<FilterValue>('all');
  const [certainty, setCertainty] = useState<FilterValue>('all');
  const [urgency, setUrgency] = useState<FilterValue>('all');
  const [state, setState] = useState<FilterValue>('all');
  const sources = useMemo(
    () =>
      [
        ...new Map(alerts.map((alert) => [alert.source_id, alert.publisher])).entries(),
      ].sort((left, right) => left[1].localeCompare(right[1])),
    [alerts],
  );
  const normalizedEvent = eventType.trim().toLocaleLowerCase();
  const visible = alerts.filter(
    (alert) =>
      (source === 'all' || alert.source_id === source) &&
      (!normalizedEvent || alert.event.toLocaleLowerCase().includes(normalizedEvent)) &&
      (severity === 'all' || alert.severity === severity) &&
      (certainty === 'all' || alert.certainty === certainty) &&
      (urgency === 'all' || alert.urgency === urgency) &&
      (state === 'all' || (alert.lifecycle_state ?? 'active') === state),
  );

  return (
    <div className="authority-warning-list">
      <fieldset className="warning-filters">
        <legend>Filter official warnings</legend>
        <label>
          <span>Source</span>
          <select value={source} onChange={(event) => setSource(event.target.value)}>
            <option value="all">All authorities</option>
            {sources.map(([id, publisher]) => (
              <option key={id} value={id}>
                {publisher}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Hazard / event type</span>
          <input
            type="search"
            value={eventType}
            onChange={(event) => setEventType(event.target.value)}
          />
        </label>
        <EnumFilter
          label="Warning severity"
          value={severity}
          values={
            [
              'extreme',
              'severe',
              'moderate',
              'minor',
              'unknown',
            ] satisfies WeatherAlertSeverity[]
          }
          onChange={setSeverity}
        />
        <EnumFilter
          label="Warning certainty"
          value={certainty}
          values={
            [
              'observed',
              'likely',
              'possible',
              'unlikely',
              'unknown',
            ] satisfies WeatherAlertCertainty[]
          }
          onChange={setCertainty}
        />
        <EnumFilter
          label="Warning urgency"
          value={urgency}
          values={
            [
              'immediate',
              'expected',
              'future',
              'past',
              'unknown',
            ] satisfies WeatherAlertUrgency[]
          }
          onChange={setUrgency}
        />
        <EnumFilter
          label="Warning state"
          value={state}
          values={['active', 'expired', 'cancelled']}
          onChange={setState}
        />
      </fieldset>
      {visible.length ? (
        <ul>
          {visible.map((alert) => (
            <li key={`${alert.sender ?? alert.source_id}:${alert.provider_alert_id}`}>
              <strong>{alert.event}</strong>
              <span>{alert.affected_area}</span>
              <small>
                Issuer: {alert.publisher} ({alert.sender ?? alert.source_id})
              </small>
              <small>
                {alert.severity} severity · {alert.urgency} urgency · {alert.certainty}{' '}
                certainty · {alert.lifecycle_state ?? 'active'}
              </small>
              <small>
                Valid: {alert.effective ?? alert.sent ?? 'not reported'} to{' '}
                {alert.expires ?? 'not reported'}
              </small>
              <small>
                {alert.geometry
                  ? 'Source polygon displayed'
                  : 'No source polygon supplied'}
              </small>
              {alert.canonical_url ? (
                <a href={alert.canonical_url} target="_blank" rel="noreferrer">
                  Open source alert
                </a>
              ) : null}
            </li>
          ))}
        </ul>
      ) : (
        <p>No warnings match the selected authority and CAP filters.</p>
      )}
    </div>
  );
}

function EnumFilter({
  label,
  value,
  values,
  onChange,
}: {
  label: string;
  value: FilterValue;
  values: readonly string[];
  onChange: (value: string) => void;
}) {
  return (
    <label>
      <span>{label}</span>
      <select
        aria-label={label}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="all">All</option>
        {values.map((item) => (
          <option key={item} value={item}>
            {item.replaceAll('_', ' ')}
          </option>
        ))}
      </select>
    </label>
  );
}
