import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { AssistantPanel } from '@/features/assistant/ui/AssistantPanel';
import { commonOperationalPicture, multimodalState } from './fixtures/multimodal';

describe('AssistantPanel', () => {
  it('submits a question and renders the conversation', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(
      <AssistantPanel
        messages={[{ id: 'a1', role: 'assistant', content: 'Ready.' }]}
        status="idle"
        error={null}
        onSubmit={onSubmit}
        onClear={vi.fn()}
      />,
    );

    await user.type(screen.getByLabelText('Question'), 'What does this map show?');
    await user.click(screen.getByRole('button', { name: 'Ask assistant' }));

    expect(onSubmit).toHaveBeenCalledWith('What does this map show?');
    expect(screen.getByText('Ready.')).toBeInTheDocument();
  });

  it('shows loading and error states', () => {
    const { rerender } = render(
      <AssistantPanel
        messages={[]}
        status="loading"
        error={null}
        onSubmit={vi.fn()}
        onClear={vi.fn()}
      />,
    );
    expect(screen.getByText('Thinking locally…')).toBeInTheDocument();

    rerender(
      <AssistantPanel
        messages={[]}
        status="error"
        error="The local backend is unavailable."
        onSubmit={vi.fn()}
        onClear={vi.fn()}
      />,
    );
    expect(screen.getByRole('alert')).toHaveTextContent('local backend');
  });

  it('renders structured report sections, warnings, links, and freshness', () => {
    render(
      <AssistantPanel
        messages={[
          {
            id: 'report-1',
            role: 'assistant',
            content: 'Source-backed report text.',
            report: {
              responseType: 'current_disaster',
              partial: true,
              warnings: ['Situation source unavailable.'],
              sections: [
                { title: 'Situation summary', content: 'A quake was identified.' },
                {
                  title: 'Physical and infrastructure damage',
                  content: 'No reliable figure yet.',
                },
              ],
              sources: [
                {
                  source_id: 'jma-rolling-earthquakes',
                  publisher: 'JMA',
                  title: 'Earthquake fixture',
                  canonical_url: 'https://example.test/event',
                  published_at: '2026-08-05T11:00:00Z',
                  retrieved_at: '2026-08-05T12:00:00Z',
                },
              ],
              investigation: {
                status: 'partial',
                task_summary: 'Latest earthquake in Japan',
                hazard: 'earthquake',
                country: 'JPN',
                information_needs: ['event_overview'],
                output_modalities: ['text'],
                actions: [
                  'Selected JMA and USGS event sources.',
                  'Selected the Ishikawa event.',
                ],
                source_ids: ['jma-rolling-earthquakes', 'usgs-earthquakes'],
                evidence_count: 1,
                capability_gaps: [
                  'Trusted disaster-image retrieval is not implemented.',
                ],
                termination_reason: 'partial_evidence',
                triage_priority: 'critical',
                triage_score: 100,
                triage_action: 'escalate_critical',
                triage_autonomy_mode: 'human_in_the_loop',
                triage_requires_human_intervention: true,
                decision_action: 'none',
                decision_autonomy_mode: 'advisory_only',
                decision_requires_human_intervention: true,
                decision_termination_reason: 'advisory_recommendation_unavailable',
                decision_state_revision: 0,
                decision_active_internal_states: [],
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

    expect(
      screen.getByRole('heading', { name: 'Situation summary' }),
    ).toBeInTheDocument();
    expect(screen.getByText('Situation source unavailable.')).toBeInTheDocument();
    expect(
      screen.getByRole('link', { name: /JMA: Earthquake fixture/ }),
    ).toHaveAttribute('href', 'https://example.test/event');
    expect(screen.getByText(/Retrieved:/)).toBeInTheDocument();
    expect(screen.getByText('Investigation details')).toBeInTheDocument();
    expect(screen.getByText('Selected the Ishikawa event.')).toBeInTheDocument();
    expect(screen.getByText(/Internal triage:/)).toHaveTextContent(
      'critical / escalate_critical / human_in_the_loop / Human intervention required',
    );
    expect(screen.getByText(/Bounded decision:/)).toHaveTextContent(
      'none / advisory_only / state r0 / Human intervention required',
    );
    expect(
      screen.getByText('Trusted disaster-image retrieval is not implemented.'),
    ).toBeInTheDocument();
  });

  it('labels visual observations and COP geometry as analytical with provenance', () => {
    render(
      <AssistantPanel
        messages={[
          {
            id: 'multimodal-report',
            role: 'assistant',
            content: 'Bounded visual analysis completed.',
            report: {
              responseType: 'current_disaster',
              warnings: [],
              sections: [],
              sources: [],
              partial: false,
              multimodal: multimodalState,
              commonOperationalPicture,
            },
          },
        ]}
        status="idle"
        error={null}
        onSubmit={vi.fn()}
        onClear={vi.fn()}
      />,
    );

    expect(
      screen.getByRole('heading', { name: 'Analytical visual evidence' }),
    ).toBeInTheDocument();
    expect(screen.getAllByText(/Analytical · AI-generated/).length).toBeGreaterThan(0);
    expect(screen.getByText(/Visible damage: major damage/)).toBeInTheDocument();
    expect(screen.getAllByText(/Licensed operator fixture/).length).toBeGreaterThan(0);
    expect(
      screen.getByText(/Uncertainty: Analytical estimate only/),
    ).toBeInTheDocument();
  });
});
