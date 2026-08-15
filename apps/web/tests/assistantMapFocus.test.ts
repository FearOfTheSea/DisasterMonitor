import { describe, expect, it } from 'vitest';

import { assistantMapAreaOfInterest } from '@/features/map/model/assistantMapFocus';
import type { ConversationMessage } from '@/shared/types/assistant';
import { commonOperationalPicture } from './fixtures/multimodal';

function assistantMessage(
  report: NonNullable<ConversationMessage['report']>,
): ConversationMessage {
  return {
    id: 'assistant-1',
    role: 'assistant',
    content: 'Source-backed result',
    report,
  };
}

const baseReport: NonNullable<ConversationMessage['report']> = {
  responseType: 'current_disaster',
  sources: [],
  warnings: [],
  sections: [],
  partial: false,
};

const selectedEvent = {
  event_id: 'jma:fixture-event',
  hazard: 'earthquake',
  location: 'Ishikawa, Japan',
  event_time: '2026-08-05T11:00:00Z',
  latitude: 37,
  longitude: 137,
  source: {
    source_id: 'jma-rolling-earthquakes',
    publisher: 'JMA',
    title: 'Earthquake fixture',
    canonical_url: 'https://example.test/event',
    retrieved_at: '2026-08-05T12:00:00Z',
  },
};

describe('assistantMapAreaOfInterest', () => {
  it('executes an explicit agent viewport action without requiring a report', () => {
    const result = assistantMapAreaOfInterest([
      {
        id: 'assistant-map-action',
        role: 'assistant',
        content: 'Showing Japan on the map.',
        mapAction: {
          type: 'fit_bounds',
          bounds: [122, 20, 154, 46],
          label: 'Japan',
          max_zoom: 8,
        },
      },
    ]);

    expect(result).toEqual({
      id: 'assistant-map-action:action:fit_bounds',
      bounds: [122, 20, 154, 46],
      maxZoom: 8,
    });
  });

  it('prefers the tighter common-operational-picture extent', () => {
    const result = assistantMapAreaOfInterest([
      assistantMessage({
        ...baseReport,
        investigation: {
          status: 'completed',
          task_summary: 'Current flood information in Vietnam',
          hazard: 'flood',
          country: 'Vietnam',
          information_needs: [],
          output_modalities: [],
          actions: [],
          source_ids: [],
          evidence_count: 1,
          capability_gaps: [],
          termination_reason: 'completed',
        },
        commonOperationalPicture: {
          cop_id: 'cop-1',
          physical_event_id: 'event-1',
          multimodal_state_version: 'mm-1',
          created_at: '2026-08-15T00:00:00Z',
          updated_at: '2026-08-15T00:00:00Z',
          status: 'current',
          layers: [
            {
              layer_type: 'source',
              layer_id: 'layer-1',
              physical_event_id: 'event-1',
              title: 'Flood extent',
              semantic_kind: 'flood_extent',
              source_ids: ['source-1'],
              source_asset_ids: ['asset-1'],
              created_at: '2026-08-15T00:00:00Z',
              updated_at: '2026-08-15T00:00:00Z',
              status: 'current',
              uncertainty: 'low',
              attribution: 'source',
              features: [
                {
                  feature_type: 'source',
                  feature_id: 'feature-1',
                  physical_event_id: 'event-1',
                  source_asset_ids: ['asset-1'],
                  created_at: '2026-08-15T00:00:00Z',
                  semantic_kind: 'flood_extent',
                  geometry: {
                    type: 'Polygon',
                    coordinates: [
                      [
                        [105, 20],
                        [107, 20],
                        [107, 22],
                        [105, 22],
                        [105, 20],
                      ],
                    ],
                    crs: 'EPSG:4326',
                  },
                  attribution: 'source',
                  status: 'current',
                  uncertainty: 'low',
                  source_id: 'source-1',
                  authority: 'official_source',
                  source_authority: 'official',
                },
              ],
            },
          ],
        },
      }),
    ]);

    expect(result).toEqual({
      id: 'assistant-1:cop:cop-1',
      bounds: [105, 20, 107, 22],
    });
  });

  it('focuses the source-backed selected event before the country fallback', () => {
    const result = assistantMapAreaOfInterest([
      assistantMessage({
        ...baseReport,
        selectedEvent,
        investigation: {
          status: 'completed',
          task_summary: 'Current earthquake information in Japan',
          hazard: 'earthquake',
          country: 'JPN',
          information_needs: [],
          output_modalities: [],
          actions: [],
          source_ids: [],
          evidence_count: 1,
          capability_gaps: [],
          termination_reason: 'completed',
        },
      }),
    ]);

    expect(result).toEqual({
      id: 'assistant-1:event:jma:fixture-event',
      bounds: [137, 37, 137, 37],
    });
  });

  it('does not invent a focus when selected-event coordinates are invalid', () => {
    const result = assistantMapAreaOfInterest([
      assistantMessage({
        ...baseReport,
        selectedEvent: { ...selectedEvent, latitude: 91, longitude: undefined },
        investigation: {
          status: 'completed',
          task_summary: 'Current earthquake information in Japan',
          hazard: 'earthquake',
          country: ' japan ',
          information_needs: [],
          output_modalities: [],
          actions: [],
          source_ids: [],
          evidence_count: 1,
          capability_gaps: [],
          termination_reason: 'completed',
        },
      }),
    ]);

    expect(result).toBeUndefined();
  });

  it('uses the short wrapped extent for COP geometry crossing the antimeridian', () => {
    const cop = structuredClone(commonOperationalPicture);
    cop.cop_id = 'cop-dateline';
    cop.layers[0].features[0].geometry = {
      type: 'LineString',
      coordinates: [
        [179, 10],
        [-179, 12],
      ],
      crs: 'EPSG:4326',
    };

    const result = assistantMapAreaOfInterest([
      assistantMessage({ ...baseReport, commonOperationalPicture: cop }),
    ]);

    expect(result).toEqual({
      id: 'assistant-1:cop:cop-dateline',
      bounds: [179, 10, 181, 12],
    });
  });

  it('does not refocus while a new user message is awaiting a reply', () => {
    const result = assistantMapAreaOfInterest([
      assistantMessage({
        ...baseReport,
        investigation: {
          status: 'completed',
          task_summary: 'Current earthquake information in Japan',
          hazard: 'earthquake',
          country: 'Japan',
          information_needs: [],
          output_modalities: [],
          actions: [],
          source_ids: [],
          evidence_count: 1,
          capability_gaps: [],
          termination_reason: 'completed',
        },
      }),
      { id: 'user-2', role: 'user', content: 'What about casualties?' },
    ]);

    expect(result).toBeUndefined();
  });

  it('does not invent an extent for unsupported country labels', () => {
    const result = assistantMapAreaOfInterest([
      assistantMessage({
        ...baseReport,
        investigation: {
          status: 'completed',
          task_summary: 'Other area',
          country: 'Atlantis',
          information_needs: [],
          output_modalities: [],
          actions: [],
          source_ids: [],
          evidence_count: 0,
          capability_gaps: [],
          termination_reason: 'completed',
        },
      }),
    ]);

    expect(result).toBeUndefined();
  });
});
