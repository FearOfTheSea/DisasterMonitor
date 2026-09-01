import type { MapAreaBounds } from '@/features/map/model/assistantMapFocus';
import type { MapView } from '@/shared/types/assistant';

export const REGIONAL_PRESET_IDS = [
  'global',
  'americas',
  'europe',
  'africa',
  'mena',
  'south-asia',
  'east-asia',
  'southeast-asia',
  'oceania',
] as const;

export type RegionalPresetId = (typeof REGIONAL_PRESET_IDS)[number];
export type RegionalSelection = RegionalPresetId | 'custom';

export type RegionalPreset = {
  id: RegionalPresetId;
  label: string;
  bounds: MapAreaBounds;
  view: MapView;
};

export const REGIONAL_PRESETS: readonly RegionalPreset[] = [
  {
    id: 'global',
    label: 'Global',
    bounds: [-180, -85, 180, 85],
    view: { centerLatitude: 0, centerLongitude: 0, zoom: 2 },
  },
  {
    id: 'americas',
    label: 'Americas',
    bounds: [-170, -60, -25, 75],
    view: { centerLatitude: 8, centerLongitude: -82, zoom: 3 },
  },
  {
    id: 'europe',
    label: 'Europe',
    bounds: [-25, 34, 45, 72],
    view: { centerLatitude: 54, centerLongitude: 15, zoom: 4 },
  },
  {
    id: 'africa',
    label: 'Africa',
    bounds: [-20, -36, 55, 38],
    view: { centerLatitude: 1, centerLongitude: 20, zoom: 3.4 },
  },
  {
    id: 'mena',
    label: 'MENA',
    bounds: [-18, 12, 65, 42],
    view: { centerLatitude: 27, centerLongitude: 42, zoom: 4 },
  },
  {
    id: 'south-asia',
    label: 'South Asia',
    bounds: [58, 5, 98, 38],
    view: { centerLatitude: 22, centerLongitude: 78, zoom: 4 },
  },
  {
    id: 'east-asia',
    label: 'East Asia',
    bounds: [98, 18, 150, 55],
    view: { centerLatitude: 35, centerLongitude: 120, zoom: 4 },
  },
  {
    id: 'southeast-asia',
    label: 'Southeast Asia',
    bounds: [90, -12, 142, 28],
    view: { centerLatitude: 10, centerLongitude: 107, zoom: 4.3 },
  },
  {
    id: 'oceania',
    label: 'Oceania',
    bounds: [105, -50, 180, 5],
    view: { centerLatitude: -23, centerLongitude: 135, zoom: 3.5 },
  },
];

const PRESETS_BY_ID = new Map(REGIONAL_PRESETS.map((preset) => [preset.id, preset]));

export function regionalPreset(id: RegionalPresetId): RegionalPreset {
  return PRESETS_BY_ID.get(id) as RegionalPreset;
}

export function applyRegionalPreset(id: RegionalPresetId): {
  regionalPreset: RegionalPresetId;
  view: MapView;
} {
  return { regionalPreset: id, view: { ...regionalPreset(id).view } };
}

export function viewMatchesRegionalPreset(
  view: MapView,
  presetId: RegionalPresetId,
): boolean {
  const target = regionalPreset(presetId).view;
  return (
    Math.abs(view.centerLatitude - target.centerLatitude) <= 0.05 &&
    Math.abs(view.centerLongitude - target.centerLongitude) <= 0.05 &&
    Math.abs(view.zoom - target.zoom) <= 0.15
  );
}

export function regionalPresetAfterViewChange(
  selected: RegionalSelection,
  view: MapView,
): RegionalSelection {
  return selected !== 'custom' && viewMatchesRegionalPreset(view, selected)
    ? selected
    : 'custom';
}
