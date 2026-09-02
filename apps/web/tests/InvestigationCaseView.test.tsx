import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { InvestigationCaseView } from '@/features/assistant/ui/InvestigationCaseView';

describe('InvestigationCaseView', () => {
  it('keeps a spatiotemporal association distinct from causation', () => {
    render(
      <InvestigationCaseView
        investigationCase={{
          case_id: 'case-1',
          country: { country_code: 'JPN', country_name: 'Japan' },
          status: 'partial',
          partial: true,
          targets: [
            {
              target_id: 'target-quake',
              disaster: 'earthquake',
              status: 'completed',
              selected_event: null,
              sources: [],
              warnings: [],
              sections: [],
              partial: false,
              termination_reason: 'grounded_answer_composed',
            },
            {
              target_id: 'target-slide',
              disaster: 'landslide',
              status: 'coverage_unavailable',
              selected_event: null,
              sources: [],
              warnings: ['No matching event.'],
              sections: [],
              partial: true,
              termination_reason: 'coverage_unavailable',
            },
          ],
          cross_hazard_assessment: {
            status: 'associated',
            summary: 'The maintained rule found a spatiotemporal association.',
            limitation: 'Spatial and temporal proximity does not establish causation.',
          },
          correlations: [
            {
              correlation_id: 'correlation-1',
              rule_id: 'compound-hazard:earthquake-landslide:v1',
              relationship: 'spatiotemporal_association',
              first_event_id: 'quake',
              first_physical_event_id: null,
              first_disaster: 'earthquake',
              second_event_id: 'slide',
              second_physical_event_id: null,
              second_disaster: 'landslide',
              distance_km: 22.2,
              time_delta_seconds: 3600,
              source_ids: ['fixture'],
              summary: 'The events are close.',
              limitation:
                'Spatial and temporal proximity does not establish causation.',
            },
          ],
        }}
      />,
    );

    expect(screen.getByText('Earthquake')).toBeVisible();
    expect(screen.getByText('Landslide')).toBeVisible();
    expect(screen.getByText('Partial investigation')).toBeVisible();
    expect(screen.getByText('Spatiotemporal association')).toBeVisible();
    expect(screen.getAllByText(/does not establish causation/i)).not.toHaveLength(0);
    expect(screen.queryByText(/caused/i)).not.toBeInTheDocument();
  });
});
