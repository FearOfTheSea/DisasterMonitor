'use client';

import { type ReactNode, useEffect, useRef, useState } from 'react';

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
  showTimeControls?: boolean;
  basemap?: 'atlas' | 'streets';
  onBasemapChange?: (basemap: 'atlas' | 'streets') => void;
  atlasIsGeneralized?: boolean;
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
  showTimeControls = true,
  basemap = 'atlas',
  onBasemapChange,
  atlasIsGeneralized = false,
}: MapLayerControlsProps) {
  const controlRef = useRef<HTMLElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const [expanded, setExpanded] = useState(false);
  const [supplementalExpanded, setSupplementalExpanded] = useState(false);
  const [explainedLayerId, setExplainedLayerId] = useState<MapLayerId>();
  const explainedLayer = explainedLayerId
    ? mapLayerDefinition(explainedLayerId)
    : undefined;
  const explainedRuntime = explainedLayerId
    ? runtimeDetails?.[explainedLayerId]
    : undefined;

  useEffect(() => {
    if (!expanded) return;
    const dismiss = (event: MouseEvent | KeyboardEvent) => {
      if (event instanceof KeyboardEvent) {
        if (event.key === 'Escape') {
          setExpanded(false);
          triggerRef.current?.focus();
        }
      } else if (
        event.target instanceof Node &&
        !controlRef.current?.contains(event.target)
      ) {
        setExpanded(false);
      }
    };
    document.addEventListener('mousedown', dismiss);
    document.addEventListener('keydown', dismiss);
    return () => {
      document.removeEventListener('mousedown', dismiss);
      document.removeEventListener('keydown', dismiss);
    };
  }, [expanded]);

  return (
    <section
      ref={controlRef}
      className={`map-layer-controls${expanded ? ' map-layer-controls-expanded' : ''}`}
      aria-label="Map layers and display time"
    >
      <button
        ref={triggerRef}
        className="map-layer-toggle"
        type="button"
        aria-label="Layers"
        aria-expanded={expanded}
        aria-controls="map-layer-options"
        onClick={() => setExpanded((value) => !value)}
      >
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.7"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="m12 3 9 5-9 5-9-5 9-5Zm-9 9 9 5 9-5M3 16l9 5 9-5" />
        </svg>
        <span>Layers</span>
        <svg
          className="disclosure-chevron"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.7"
          aria-hidden="true"
        >
          <path d="m7 10 5 5 5-5" />
        </svg>
      </button>
      {expanded && (
        <div id="map-layer-options" className="map-layer-options">
          <div className="map-layer-controls-heading">
            <div>
              <span>Map display</span>
              <h2>Layers</h2>
            </div>
            <output>{state.timeWindow}</output>
          </div>
          {onBasemapChange ? (
            <fieldset className="basemap-switcher">
              <legend>Basemap</legend>
              <div>
                <button
                  type="button"
                  aria-pressed={basemap === 'atlas'}
                  onClick={() => onBasemapChange('atlas')}
                >
                  Atlas
                </button>
                <button
                  type="button"
                  aria-pressed={basemap === 'streets'}
                  onClick={() => onBasemapChange('streets')}
                >
                  Streets
                </button>
              </div>
              {basemap === 'atlas' && atlasIsGeneralized ? (
                <small>
                  Atlas geography is generalized at this scale.{' '}
                  <button type="button" onClick={() => onBasemapChange('streets')}>
                    Switch to Streets
                  </button>
                </small>
              ) : null}
            </fieldset>
          ) : null}
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
          {showTimeControls && (
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
              <small>
                Changes displayed records only; provider coverage is unchanged.
              </small>
            </fieldset>
          )}
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
          {supplemental ? (
            <div className="map-layer-supplemental">
              <button
                type="button"
                aria-label="Browse authoritative alerts"
                aria-expanded={supplementalExpanded}
                aria-controls="map-layer-supplemental-content"
                onClick={() => setSupplementalExpanded((value) => !value)}
              >
                <span>
                  <b>Browse authoritative alerts</b>
                  <small>Filters and source records</small>
                </span>
                <svg
                  className="disclosure-chevron"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.7"
                  aria-hidden="true"
                >
                  <path d="m7 10 5 5 5-5" />
                </svg>
              </button>
              {supplementalExpanded ? (
                <div id="map-layer-supplemental-content">{supplemental}</div>
              ) : null}
            </div>
          ) : null}
          {explainedLayer ? (
            <LayerExplanation
              layer={explainedLayer}
              onClose={() => setExplainedLayerId(undefined)}
              sourceDetail={explainedRuntime?.sourceDetail}
              freshnessDetail={explainedRuntime?.freshnessDetail}
              attribution={explainedRuntime?.attribution}
            />
          ) : null}
        </div>
      )}
    </section>
  );
}
