import { render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';

import { AssistantPanel } from '@/features/assistant/ui/AssistantPanel';

it('does not show a neutral prior as a human impact probability', () => {
  render(
    <AssistantPanel
      messages={[
        {
          id: 'unsupported-estimate',
          role: 'assistant',
          content: 'Human impact remains unknown.',
          report: {
            responseType: 'current_disaster',
            warnings: [],
            sections: [],
            sources: [],
            partial: true,
            claims: [],
            timeline: [],
            decisionSupport: {
              artifact_id: 'decision-support:unresolved',
              evidence_state_version: 'evidence-state:unresolved',
              facts: [],
              estimates: [
                {
                  estimate_id: 'hypothesis:unresolved',
                  proposition: 'The event has material human impact.',
                  probability: 0.5,
                  supporting_evidence_ids: [],
                  contradicting_evidence_ids: [],
                  uncertain_evidence_ids: [],
                  rationale_rule_ids: ['ew.hypothesis.no_decisive_current_observation'],
                  statement_type: 'estimate',
                },
              ],
              scenario_mode: 'unresolved',
              recommendation_status: 'disabled_unsupported_premise',
              advisory_only: true,
            },
          },
        },
      ]}
      status="idle"
      error={null}
      onSubmit={vi.fn()}
      onClear={vi.fn()}
    />,
  );

  expect(screen.getByText('Human impact remains unresolved.')).toBeInTheDocument();
  expect(screen.queryByText('50% estimated probability')).not.toBeInTheDocument();
});
