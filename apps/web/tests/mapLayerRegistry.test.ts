import { describe, expect, it } from 'vitest';

import {
  MAP_LAYER_REGISTRY,
  mapLayerDefinition,
} from '@/features/map/model/mapLayerRegistry';
import {
  applyMapLayerPreset,
  createDefaultMapLayerState,
  filterCorrelationsForDisplay,
  filterIncidentsForDisplay,
  setMapLayerVisibility,
} from '@/features/map/model/mapLayerState';
import type {
  ActiveIncident,
  CompoundHazardCorrelation,
} from '@/features/incidents/model/activeIncidents';

function incident(eventId: string, eventTime: string): ActiveIncident {
  return {
    event_id: eventId,
    disaster: eventId.startsWith('flood') ? 'flood' : 'earthquake',
    location: eventId,
    event_time: eventTime,
    geometry: {
      kind: 'point',
      coordinates: [{ latitude: 10, longitude: 20 }],
      description: null,
      source_id: 'fixture-source',
      estimated: false,
    },
    measurements: [],
    provider_ids: ['fixture-provider'],
    provider_tier: 'primary',
    source_authority: 'scientific_authority',
    source: {
      source_id: 'fixture-source',
      publisher: 'Fixture source',
      title: 'Fixture record',
      canonical_url: 'https://example.test/fixture',
      published_at: eventTime,
      updated_at: null,
      retrieved_at: '2026-09-01T12:00:00Z',
      snapshot_id: null,
    },
  };
}

const CORRELATION: CompoundHazardCorrelation = {
  correlation_id: 'correlation:fixture',
  rule_id: 'compound-hazard:fixture:v1',
  relationship: 'spatiotemporal_association',
  first_event_id: 'earthquake-recent',
  first_physical_event_id: null,
  first_disaster: 'earthquake',
  second_event_id: 'flood-recent',
  second_physical_event_id: null,
  second_disaster: 'flood',
  distance_km: 20,
  time_delta_seconds: 900,
  source_ids: ['fixture-source'],
  summary: 'Two fixture records are near in space and time.',
  limitation: 'Spatial and temporal proximity does not establish causation.',
};

describe('map layer registry', () => {
  it('defines one complete typed registry for every current operator layer', () => {
    expect(MAP_LAYER_REGISTRY.map((layer) => layer.id)).toEqual([
      'active-incidents',
      'satellite-imagery',
      'cop-evidence',
      'cyclone-supplemental',
      'authoritative-weather-alerts',
      'compound-correlations',
    ]);

    for (const layer of MAP_LAYER_REGISTRY) {
      expect(layer.label).not.toBe('');
      expect(layer.category).not.toBe('');
      expect(layer.purpose).not.toBe('');
      expect(layer.sourceDescription).not.toBe('');
      expect(layer.freshnessSemantics).not.toBe('');
      expect(layer.authorityDescription).not.toBe('');
      expect(layer.limitations.length).toBeGreaterThan(0);
      expect(typeof layer.defaultVisible).toBe('boolean');
      expect(mapLayerDefinition(layer.id)).toBe(layer);
    }

    expect(mapLayerDefinition('satellite-imagery').limitations.join(' ')).toMatch(
      /not live/i,
    );
    expect(mapLayerDefinition('cyclone-supplemental').limitations.join(' ')).toMatch(
      /not observed.*footprint/i,
    );
    expect(
      mapLayerDefinition('authoritative-weather-alerts').limitations.join(' '),
    ).toMatch(/not global/i);
    expect(mapLayerDefinition('compound-correlations').limitations.join(' ')).toMatch(
      /does not establish causation/i,
    );
  });

  it('applies deterministic presets and independent layer toggles', () => {
    const initial = createDefaultMapLayerState();
    const satellite = applyMapLayerPreset(initial, 'satellite');

    expect(satellite.visibility).toEqual({
      'active-incidents': true,
      'satellite-imagery': true,
      'cop-evidence': false,
      'cyclone-supplemental': false,
      'authoritative-weather-alerts': false,
      'compound-correlations': false,
    });
    expect(satellite.timeWindow).toBe(initial.timeWindow);

    expect(setMapLayerVisibility(satellite, 'cop-evidence', true)).toEqual({
      ...satellite,
      activePreset: undefined,
      visibility: { ...satellite.visibility, 'cop-evidence': true },
    });

    expect(
      applyMapLayerPreset(initial, 'warnings').visibility[
        'authoritative-weather-alerts'
      ],
    ).toBe(true);

    expect(applyMapLayerPreset(initial, 'all').visibility).toEqual(
      Object.fromEntries(MAP_LAYER_REGISTRY.map((layer) => [layer.id, true])),
    );
  });

  it('filters only display records against the trusted snapshot retrieval time', () => {
    const records = [
      incident('earthquake-recent', '2026-09-01T11:30:00Z'),
      incident('flood-recent', '2026-09-01T11:45:00Z'),
      incident('earthquake-old', '2026-09-01T05:00:00Z'),
    ];

    expect(
      filterIncidentsForDisplay(records, '2026-09-01T12:00:00Z', '1h').map(
        (item) => item.event_id,
      ),
    ).toEqual(['earthquake-recent', 'flood-recent']);
    expect(filterIncidentsForDisplay(records, '2026-09-01T12:00:00Z', '24h')).toEqual(
      records,
    );
    expect(
      filterCorrelationsForDisplay(
        [CORRELATION],
        records,
        '2026-09-01T12:00:00Z',
        '1h',
      ),
    ).toEqual([CORRELATION]);
    expect(
      filterCorrelationsForDisplay(
        [{ ...CORRELATION, second_event_id: 'earthquake-old' }],
        records,
        '2026-09-01T12:00:00Z',
        '1h',
      ),
    ).toEqual([]);
  });
});
