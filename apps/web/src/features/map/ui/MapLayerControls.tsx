'use client';

import { type ReactNode, useState } from 'react';

import {
  MAP_LAYER_REGISTRY,
  mapLayerDefinition,
  type MapLayerId,
} from '@/features/map/model/mapLayerRegistry';
import {
  applyMapLayerPreset,
  MAP_LAYER_PRESETS,
  MAP_TIME_WINDOWS,
  setMapLayerVisibility,
  setMapTimeWindow,
  type MapLayerPreset,
  type MapLayerState,
} from '@/features/map/model/mapLayerState';
import { LayerExplanation } from '@/features/map/ui/LayerExplanation';
import {
  REGIONAL_PRESETS,
  type RegionalPresetId,
  type RegionalSelection,
} from '@/features/map/model/regionalPresets';

type LayerRuntimeDetail = {
  available: boolean;
  availabilityLabel: string;
  sourceDetail?: string;
  freshnessDetail?: string;
  attribution?: string;
};

type MapLayerControlsProps = {
  state: MapLayerState;
  onChange: (state: MapLayerState) => void;
  runtimeDetails?: Partial<Record<MapLayerId, LayerRuntimeDetail>>;
  children?: ReactNode;
  supplemental?: ReactNode;
  regionalSelection?: RegionalSelection;
  onRegionalSelectionChange?: (preset: RegionalPresetId) => void;
};

const PRESET_LABELS: Record<MapLayerPreset, string> = {
  minimal: 'Minimal',
  incidents: 'Incidents',
  evidence: 'Evidence',
  forecasts: 'Forecasts',
  warnings: 'Warnings',
  satellite: 'Satellite',
  all: 'All',
};

export function MapLayerControls({
  state,
  onChange,
  runtimeDetails,
  children,
  supplemental,
  regionalSelection = 'custom',
  onRegionalSelectionChange,
}: MapLayerControlsProps) {
  const [explainedLayerId, setExplainedLayerId] = useState<MapLayerId>();
  const explainedLayer = explainedLayerId
    ? mapLayerDefinition(explainedLayerId)
    : undefined;
  const explainedRuntime = explainedLayerId
    ? runtimeDetails?.[explainedLayerId]
    : undefined;

  return (
    <section className="map-layer-controls" aria-label="Map layers and display time">
      <div className="map-layer-controls-heading">
        <div>
          <span>Map display</span>
          <h2>Layers</h2>
        </div>
        <output>{state.timeWindow}</output>
      </div>
      <div className="map-layer-presets" aria-label="Layer presets">
        {MAP_LAYER_PRESETS.map((preset) => (
          <button
            key={preset}
            type="button"
            aria-label={`${PRESET_LABELS[preset]} preset`}
            aria-pressed={state.activePreset === preset}
            onClick={() => onChange(applyMapLayerPreset(state, preset))}
          >
            {PRESET_LABELS[preset]}
          </button>
        ))}
      </div>
      {onRegionalSelectionChange ? (
        <fieldset className="regional-preset-controls">
          <legend>Regional navigation</legend>
          <div>
            {REGIONAL_PRESETS.map((preset) => (
              <button
                key={preset.id}
                type="button"
                aria-label={`Focus ${preset.label}`}
                aria-pressed={regionalSelection === preset.id}
                onClick={() => onRegionalSelectionChange(preset.id)}
              >
                {preset.label}
              </button>
            ))}
          </div>
          <small>
            Presentation-only navigation; presets do not define disaster geography.
          </small>
        </fieldset>
      ) : null}
      <fieldset className="map-time-filter">
        <legend>Display time</legend>
        <div>
          {MAP_TIME_WINDOWS.map((window) => (
            <label key={window}>
              <input
                type="radio"
                name="map-display-time"
                value={window}
                checked={state.timeWindow === window}
                onChange={() => onChange(setMapTimeWindow(state, window))}
              />
              <span>{window}</span>
            </label>
          ))}
        </div>
        <small>Changes displayed records only; provider coverage is unchanged.</small>
      </fieldset>
      <div className="map-layer-list">
        {MAP_LAYER_REGISTRY.map((layer) => {
          const runtime = runtimeDetails?.[layer.id];
          return (
            <div className="map-layer-row" key={layer.id}>
              <label>
                <input
                  type="checkbox"
                  aria-label={layer.label}
                  checked={state.visibility[layer.id]}
                  onChange={(event) =>
                    onChange(
                      setMapLayerVisibility(state, layer.id, event.target.checked),
                    )
                  }
                />
                <span>
                  <b>{layer.label}</b>
                  <small>{runtime?.availabilityLabel ?? layer.category}</small>
                </span>
              </label>
              <button
                type="button"
                aria-label={`About ${layer.label}`}
                aria-expanded={explainedLayerId === layer.id}
                onClick={() => setExplainedLayerId(layer.id)}
              >
                About
              </button>
            </div>
          );
        })}
      </div>
      {children ? (
        <details
          className="map-layer-satellite-controls"
          open={state.visibility['satellite-imagery']}
        >
          <summary>Satellite source settings</summary>
          {children}
        </details>
      ) : null}
      {supplemental}
      {explainedLayer ? (
        <LayerExplanation
          layer={explainedLayer}
          onClose={() => setExplainedLayerId(undefined)}
          sourceDetail={explainedRuntime?.sourceDetail}
          freshnessDetail={explainedRuntime?.freshnessDetail}
          attribution={explainedRuntime?.attribution}
        />
      ) : null}
    </section>
  );
}
