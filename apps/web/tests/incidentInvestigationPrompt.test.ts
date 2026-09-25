import { describe, expect, it } from 'vitest';

import { relatedInvestigation } from '@/features/incidents/ui/incidentPresentation';

describe('related incident investigation', () => {
  it('uses a supported country scope without promising to select the displayed event', () => {
    expect(
      relatedInvestigation({
        disaster: 'earthquake',
        country: {
          code: 'TUR',
          name: 'Turkey',
          association_basis: 'coordinate_polygon',
          distance_km: null,
        },
      }),
    ).toEqual({
      label: 'Ask about earthquakes in Turkey',
      question: 'What are the latest earthquakes in Turkey?',
    });
  });

  it('uses worldwide scope when the event has no trusted country', () => {
    expect(relatedInvestigation({ disaster: 'earthquake', country: null })).toEqual({
      label: 'Ask about worldwide earthquakes',
      question: 'What are the latest earthquakes worldwide?',
    });
  });
});
