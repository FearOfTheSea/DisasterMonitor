import { describe, expect, it } from 'vitest';

import { assistantMapAreaOfInterest } from '@/features/map/model/assistantMapFocus';
import type { ConversationMessage } from '@/shared/types/assistant';

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

describe('assistantMapAreaOfInterest', () => {
  it('fits the validated investigation country when no COP geometry exists', () => {
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
    ]);

    expect(result).toEqual({
      id: 'assistant-1:country:Japan',
      bounds: [122, 20, 154, 46],
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
