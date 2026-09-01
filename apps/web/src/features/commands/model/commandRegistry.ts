import {
  MAP_LAYER_REGISTRY,
  type MapLayerId,
} from '@/features/map/model/mapLayerRegistry';
import {
  applyMapLayerPreset,
  MAP_LAYER_PRESETS,
  MAP_TIME_WINDOWS,
  setMapLayerVisibility,
  setMapTimeWindow,
  type MapLayerState,
} from '@/features/map/model/mapLayerState';
import {
  REGIONAL_PRESETS,
  type RegionalPresetId,
} from '@/features/map/model/regionalPresets';

export type OperatorCommand = {
  id: string;
  label: string;
  group: string;
  keywords: readonly string[];
  execute: () => void;
};

type CommandIncident = {
  event_id: string;
  location: string;
  source: { title: string };
};

export type CommandRegistryContext = {
  incidents: readonly CommandIncident[];
  layerState: MapLayerState;
  selectedIncidentId?: string;
  onSelectIncident: (incidentId: string) => void;
  onFocusSelectedIncident: () => void;
  onSelectRegion: (region: RegionalPresetId) => void;
  onLayerStateChange: (state: MapLayerState) => void;
  onOpenFindings: () => void;
  onOpenSourceCatalog: () => void;
  onOpenIncidentWatches: () => void;
  onOpenOperations: () => void;
};

const PRESET_LABELS: Record<(typeof MAP_LAYER_PRESETS)[number], string> = {
  minimal: 'Minimal',
  incidents: 'Incidents',
  evidence: 'Evidence',
  forecasts: 'Forecasts',
  warnings: 'Warnings',
  satellite: 'Satellite',
  all: 'All',
};

export function buildCommandRegistry(
  context: CommandRegistryContext,
): OperatorCommand[] {
  const commands: OperatorCommand[] = [
    {
      id: 'open:findings',
      label: 'Open Findings',
      group: 'Navigation',
      keywords: ['findings', 'changes', 'coverage'],
      execute: context.onOpenFindings,
    },
    {
      id: 'open:sources',
      label: 'Open Source Catalog',
      group: 'Navigation',
      keywords: ['source', 'catalog', 'providers'],
      execute: context.onOpenSourceCatalog,
    },
    {
      id: 'open:watches',
      label: 'Open Incident Watches',
      group: 'Navigation',
      keywords: ['incident', 'watches', 'operations'],
      execute: context.onOpenIncidentWatches,
    },
    {
      id: 'open:operations',
      label: 'Open Evidence Operations',
      group: 'Navigation',
      keywords: ['operations', 'evidence', 'freshness'],
      execute: context.onOpenOperations,
    },
  ];
  if (context.selectedIncidentId) {
    commands.push({
      id: 'incident:focus-selected',
      label: 'Focus currently selected incident',
      group: 'Incidents',
      keywords: ['focus', 'selected', 'incident', 'map'],
      execute: context.onFocusSelectedIncident,
    });
  }
  commands.push(
    ...REGIONAL_PRESETS.map((preset) => ({
      id: `region:${preset.id}`,
      label: `Focus ${preset.label}`,
      group: 'Regions',
      keywords: [preset.label, 'region', 'map'],
      execute: () => context.onSelectRegion(preset.id),
    })),
  );
  commands.push(
    ...[...context.incidents]
      .sort(
        (left, right) =>
          left.source.title.localeCompare(right.source.title) ||
          left.location.localeCompare(right.location) ||
          left.event_id.localeCompare(right.event_id),
      )
      .map((incident) => ({
        id: `incident:${incident.event_id}`,
        label: `Select ${incident.source.title} — ${incident.location}`,
        group: 'Incidents',
        keywords: [incident.source.title, incident.location, incident.event_id],
        execute: () => context.onSelectIncident(incident.event_id),
      })),
  );
  commands.push(
    ...MAP_LAYER_REGISTRY.map((layer) => ({
      id: `layer:${layer.id}`,
      label: `Toggle ${layer.label}`,
      group: 'Map layers',
      keywords: [layer.label, layer.category, 'layer'],
      execute: () =>
        context.onLayerStateChange(
          setMapLayerVisibility(
            context.layerState,
            layer.id as MapLayerId,
            !context.layerState.visibility[layer.id],
          ),
        ),
    })),
  );
  commands.push(
    ...MAP_LAYER_PRESETS.map((preset) => ({
      id: `layer-preset:${preset}`,
      label: `Apply ${PRESET_LABELS[preset]} layer preset`,
      group: 'Map layers',
      keywords: [PRESET_LABELS[preset], 'preset', 'layers'],
      execute: () =>
        context.onLayerStateChange(applyMapLayerPreset(context.layerState, preset)),
    })),
  );
  commands.push(
    ...MAP_TIME_WINDOWS.map((window) => ({
      id: `time:${window}`,
      label: `Show incidents from ${window}`,
      group: 'Display time',
      keywords: [window, 'time', 'filter', 'incidents'],
      execute: () =>
        context.onLayerStateChange(setMapTimeWindow(context.layerState, window)),
    })),
  );
  return commands;
}
