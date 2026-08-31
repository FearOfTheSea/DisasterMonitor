import type { CycloneMapLayer, SelectedEvent } from '@/shared/types/assistant';

export type CycloneLayerRole = CycloneMapLayer['semantic_role'];

export type CycloneStyleSemantics = {
  label: string;
  patternLabel: 'solid' | 'dashed' | 'area-dashed' | 'dotted';
  strokeColor: string;
  fillColor: string;
  lineDash?: number[];
};

const SEMANTICS: Record<CycloneLayerRole, CycloneStyleSemantics> = {
  provisional_track: {
    label: 'Provisional track',
    patternLabel: 'solid',
    strokeColor: '#5b21b6',
    fillColor: '#5b21b626',
  },
  forecast_track: {
    label: 'Forecast track',
    patternLabel: 'dashed',
    strokeColor: '#0369a1',
    fillColor: '#0369a11f',
    lineDash: [10, 7],
  },
  uncertainty_area: {
    label: 'Forecast uncertainty',
    patternLabel: 'area-dashed',
    strokeColor: '#b45309',
    fillColor: '#f59e0b2e',
    lineDash: [5, 6],
  },
  wind_radii: {
    label: 'Wind radii',
    patternLabel: 'dotted',
    strokeColor: '#0f766e',
    fillColor: '#14b8a626',
    lineDash: [1, 6],
  },
};

export function cycloneStyleSemantics(role: CycloneLayerRole): CycloneStyleSemantics {
  return SEMANTICS[role];
}

export function cycloneMapLayers(selectedEvent?: SelectedEvent): CycloneMapLayer[] {
  return selectedEvent?.disaster === 'tropical_cyclone'
    ? (selectedEvent.supplemental_geometry ?? [])
    : [];
}
