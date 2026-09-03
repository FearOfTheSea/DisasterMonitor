import type { ActiveIncident } from '@/features/incidents/model/activeIncidents';
import { copStyleSemantics } from '@/features/map/model/copRenderPlan';
import { cycloneStyleSemantics } from '@/features/map/model/cycloneMapLayers';
import {
  observationTimeForSource,
  type SatelliteImagerySource,
  type SatelliteMapState,
  type SatelliteSourceId,
} from '@/features/map/model/satelliteImagery';
import type { WeatherAlertsSnapshot } from '@/features/weather/model/weatherAlert';
import type {
  CommonOperationalPicture,
  CycloneMapLayer,
} from '@/shared/types/assistant';

type SatelliteImageryControlsProps = {
  enabled: boolean;
  source: SatelliteImagerySource;
  sources: readonly SatelliteImagerySource[];
  state: SatelliteMapState;
  opacity: number;
  catalogUnavailable: boolean;
  onStateChange: (state: SatelliteMapState) => void;
  onOpacityChange: (opacity: number) => void;
};

export function SatelliteImageryControls({
  enabled,
  source,
  sources,
  state,
  opacity,
  catalogUnavailable,
  onStateChange,
  onOpacityChange,
}: SatelliteImageryControlsProps) {
  return (
    <fieldset className="satellite-controls">
      <legend>Satellite imagery source</legend>
      <div className="satellite-controls-heading">
        <strong>{source.provider}</strong>
        <span>{enabled ? 'Layer on' : 'Layer off'}</span>
      </div>
      <label>
        <span>Satellite source</span>
        <select
          value={state.sourceId}
          onChange={(event) => {
            const sourceId = event.target.value as SatelliteSourceId;
            const nextSource = sources.find((item) => item.id === sourceId);
            if (!nextSource) return;
            onStateChange({
              sourceId,
              observationTime: observationTimeForSource(nextSource),
            });
          }}
        >
          {sources.map((item) => (
            <option key={item.id} value={item.id} disabled={!item.available}>
              {item.displayName}
            </option>
          ))}
        </select>
      </label>
      <label>
        <span>Satellite opacity</span>
        <input
          type="range"
          min="0"
          max="1"
          step="0.05"
          value={opacity}
          disabled={!enabled}
          onChange={(event) => onOpacityChange(Number(event.target.value))}
        />
        <output>{Math.round(opacity * 100)}%</output>
      </label>
      {source.temporalMode === 'daily' ? (
        <label>
          <span>Observation date</span>
          <input
            type="date"
            value={state.observationTime ?? ''}
            disabled={!enabled}
            onChange={(event) =>
              onStateChange({
                sourceId: state.sourceId,
                observationTime: event.target.value,
              })
            }
          />
        </label>
      ) : source.temporalMode === 'subdaily' ? (
        <label>
          <span>Observation date/time (UTC)</span>
          <input
            type="datetime-local"
            step="600"
            value={state.observationTime?.slice(0, 16) ?? ''}
            disabled={!enabled}
            onChange={(event) =>
              onStateChange({
                sourceId: state.sourceId,
                observationTime: event.target.value
                  ? `${event.target.value}:00Z`
                  : undefined,
              })
            }
          />
        </label>
      ) : (
        <span className="satellite-fixed-time">
          Observation time: configured mosaic period
        </span>
      )}
      <div className="satellite-source-details" aria-live="polite">
        <span>Provider: {source.provider}</span>
        <span>
          Requested observation: {state.observationTime ?? 'configured mosaic period'}
        </span>
        <span>
          Available observation time is not reported by this client; the requested time
          may be unavailable.
        </span>
        <span>Attribution: {source.attribution}</span>
        <strong>Imagery is not live.</strong>
        {!source.available ? (
          <strong>Provider unavailable: server configuration is required.</strong>
        ) : null}
        {catalogUnavailable ? (
          <strong>
            Provider catalog unavailable; credentialed providers remain disabled.
          </strong>
        ) : null}
      </div>
    </fieldset>
  );
}

export function WeatherAlertCoverage({
  snapshot,
}: {
  snapshot: WeatherAlertsSnapshot;
}) {
  return (
    <aside className="weather-alerts-legend" aria-label="Weather alert coverage">
      <header>
        <strong>Authoritative weather alerts</strong>
        <span>{snapshot.coverage.state.replaceAll('_', ' ')}</span>
      </header>
      <p>{snapshot.coverage.detail}</p>
      <p>{snapshot.coverage.geographic_scope}</p>
      <p>
        These polygons are official warning areas, not observed disaster event
        footprints. Alerts without source geometry remain listed but are not drawn.
      </p>
      {snapshot.alerts.length > 0 ? (
        <ul>
          {snapshot.alerts.slice(0, 8).map((alert) => (
            <li key={alert.provider_alert_id}>
              <strong>{alert.event}</strong>
              <span>{alert.affected_area}</span>
              <small>
                {alert.severity} severity · {alert.urgency} urgency · {alert.certainty}{' '}
                certainty
              </small>
              <small>
                Effective {alert.effective ?? 'not reported'} · expires{' '}
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
      ) : null}
      {snapshot.alerts.length > 8 ? (
        <small>
          {snapshot.alerts.length - 8} additional active alerts omitted from this
          compact list.
        </small>
      ) : null}
      {snapshot.warnings.map((warning) => (
        <p key={`${warning.reason_code}:${warning.detail}`}>{warning.detail}</p>
      ))}
    </aside>
  );
}

type ClusteredIncident = {
  incidentId: string;
  incident: ActiveIncident;
};

export function IncidentClusterPicker({
  incidents,
  onClose,
  onSelectIncident,
}: {
  incidents: readonly ClusteredIncident[];
  onClose: () => void;
  onSelectIncident: (incidentId: string) => void;
}) {
  if (incidents.length === 0) return null;
  return (
    <aside className="incident-cluster-picker" aria-label="Clustered incidents">
      <header>
        <strong>{incidents.length} incidents at this map scale</strong>
        <button type="button" onClick={onClose}>
          Close
        </button>
      </header>
      <p>Select an underlying source record.</p>
      <ul>
        {incidents.map(({ incidentId, incident }) => (
          <li key={incidentId}>
            <button type="button" onClick={() => onSelectIncident(incidentId)}>
              {incident.location}
            </button>
          </li>
        ))}
      </ul>
    </aside>
  );
}

export function CommonOperationalPictureLegend({
  picture,
  visible,
}: {
  picture?: CommonOperationalPicture;
  visible: boolean;
}) {
  if (!picture || !visible) return null;
  return (
    <aside className="cop-legend" aria-label="Common operational picture legend">
      <strong>Common operational picture</strong>
      <span>Status: {picture.status}</span>
      <ul>
        {picture.layers.flatMap((layer) =>
          layer.features.map((feature) => {
            const semantics = copStyleSemantics(feature.authority);
            return (
              <li key={feature.feature_id}>
                <span
                  className={`legend-line legend-line-${semantics.patternLabel}`}
                  aria-hidden="true"
                />
                <span>
                  <b>{semantics.authorityLabel}</b> · {layer.title}
                  <small>
                    Layer: {layer.status} · {layer.uncertainty}
                  </small>
                  <small>
                    Feature: {feature.status} · {feature.uncertainty}
                  </small>
                  <small>Attribution: {feature.attribution}</small>
                </span>
              </li>
            );
          }),
        )}
      </ul>
    </aside>
  );
}

export function CycloneLegend({
  layers,
  visible,
}: {
  layers: readonly CycloneMapLayer[];
  visible: boolean;
}) {
  if (layers.length === 0 || !visible) return null;
  return (
    <aside className="cyclone-legend" aria-label="Cyclone forecast layers">
      <strong>Cyclone layers</strong>
      <ul>
        {layers.map((layer) => {
          const semantics = cycloneStyleSemantics(layer.semantic_role);
          const label =
            layer.semantic_role === 'wind_radii' && layer.wind_threshold
              ? `${semantics.label} · ${layer.wind_threshold} ${layer.wind_threshold_unit}`
              : semantics.label;
          return (
            <li key={layer.layer_id}>
              <span
                className={`cyclone-legend-mark cyclone-legend-${layer.semantic_role}`}
                aria-hidden="true"
              />
              <span>
                <b>{label}</b>
                <small>{layer.source.publisher}</small>
                <small>{layer.limitation}</small>
              </span>
            </li>
          );
        })}
      </ul>
      <p>Forecast and uncertainty geometry are not observed storm footprints.</p>
    </aside>
  );
}
