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
                specialist_handoff_count: 2,
                specialist_roles: [
                  'evidence_reconciliation_specialist',
                  'decision_analysis_specialist',
                ],
                collaboration_status: 'completed',
                collaboration_finding_count: 5,
                collaboration_deadlock_count: 0,
                collaboration_iterations: 1,
                collaboration_fallback_reason: null,
                coordination_supervision_id: 'coordination-supervision:fixture',
                coordination_supervisor_status: 'autonomous_complete',
                coordination_sufficient: true,
                coordination_required_finding_keys: [
                  'event_identity',
                  'decision_policy',
                ],
                coordination_missing_finding_keys: [],
                coordination_termination_reason: 'sufficient_analytical_end_state',
                coordination_final_rationale: 'The bounded checklist is complete.',
                coordination_evidence_ids: ['physical-event:fixture'],
                coordination_analytical_focus: 'material_conflicts',
                coordination_analytical_parameter_set_id:
                  'analytical-tuning:v3-governed',
                coordination_analytical_release_id:
                  'analytical-tuning-release:v3-governed',
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
    expect(screen.getByText(/Specialist handoffs:/)).toHaveTextContent(
      '2 / evidence_reconciliation_specialist, decision_analysis_specialist',
    );
    expect(screen.getByText(/Collaboration:/)).toHaveTextContent(
      'completed / 5 findings / 1 iteration(s)',
    );
    expect(screen.getByText(/Coordination supervisor:/)).toHaveTextContent(
      'autonomous_complete / sufficient / sufficient_analytical_end_state / focus material_conflicts / analytical-tuning:v3-governed / release analytical-tuning-release:v3-governed',
    );
    expect(screen.getByText('The bounded checklist is complete.')).toBeInTheDocument();
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

  it('renders source photos with caption, date, credit, and association status', () => {
    render(
      <AssistantPanel
        messages={[
          {
            id: 'media-report',
            role: 'assistant',
            content: 'Source-backed report with media.',
            report: {
              responseType: 'current_disaster',
              warnings: [],
              sections: [],
              sources: [],
              partial: false,
              mediaGallery: {
                event_id: 'us6000tjl2',
                physical_event_id: 'physical-event:colombia',
                generated_at: '2026-08-15T12:00:00Z',
                rejected_count: 1,
                provider_ids: ['bounded-news-event-media-v1'],
                warnings: [],
                items: [
                  {
                    media_id: `media:${'a'.repeat(32)}`,
                    image_url: 'http://localhost:8001/api/v1/media/fixture',
                    event_id: 'us6000tjl2',
                    physical_event_id: 'physical-event:colombia',
                    source_id: 'event-media-nbc-news',
                    publisher: 'NBC News',
                    source_page_url: 'https://www.nbcnews.com/event',
                    caption: 'Rescue workers search through rubble in Colombia.',
                    credit: 'Jane Doe / AP',
                    credit_kind: 'agency',
                    published_at: '2026-08-10T06:32:00Z',
                    captured_at: null,
                    license_name: null,
                    license_url: null,
                    rights_status: 'source_preview',
                    role: 'rescue_effort',
                    association_status: 'corroborated',
                    association_rule_ids: [
                      'media.association.publication_window',
                      'media.association.hazard_text',
                      'media.association.country_text',
                    ],
                    association_detail:
                      'Publication time, hazard, and selected-event geography agree.',
                    uncertainty: 'Source-associated preview, not a verified fact.',
                    content_sha256: 'b'.repeat(64),
                    width: 1200,
                    height: 675,
                  },
                ],
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
      screen.getByRole('heading', { name: 'Event-associated source photos' }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('img', {
        name: 'Rescue workers search through rubble in Colombia.',
      }),
    ).toBeInTheDocument();
    expect(screen.getByText(/Credit: Jane Doe \/ AP/)).toBeInTheDocument();
    expect(screen.getByText(/Published:/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Source: NBC News' })).toHaveAttribute(
      'href',
      'https://www.nbcnews.com/event',
    );
    expect(screen.getByText('corroborated')).toBeInTheDocument();
    expect(screen.getByText(/1 rejected/)).toBeInTheDocument();
  });

  it('keeps source epistemic status distinct from DM analytical estimates', () => {
    render(
      <AssistantPanel
        messages={[
          {
            id: 'decision-report',
            role: 'assistant',
            content: 'Bounded decision support completed.',
            report: {
              responseType: 'current_disaster',
              warnings: [],
              sections: [],
              sources: [],
              partial: false,
              decisionSupport: {
                artifact_id: 'decision-support:fixture',
                evidence_state_version: 'evidence-state:fixture',
                facts: [
                  {
                    fact_id: 'decision-fact:preliminary',
                    statement: 'Injuries are preliminarily reported.',
                    evidence_ids: ['observation:preliminary'],
                    source_ids: ['source:fixture'],
                    status: 'preliminary',
                    statement_type: 'preliminary_observation',
                  },
                  {
                    fact_id: 'decision-fact:estimated',
                    statement: 'A source estimates ten displaced people.',
                    evidence_ids: ['observation:estimated'],
                    source_ids: ['source:fixture'],
                    status: 'estimated',
                    statement_type: 'source_estimate',
                  },
                  {
                    fact_id: 'decision-fact:disputed',
                    statement: 'A disruption report is disputed.',
                    evidence_ids: ['observation:disputed'],
                    source_ids: ['source:fixture'],
                    status: 'disputed',
                    statement_type: 'disputed_observation',
                  },
                ],
                estimates: [
                  {
                    estimate_id: 'decision-estimate:fixture',
                    proposition: 'Material human impact is plausible.',
                    probability: 0.75,
                    supporting_evidence_ids: ['observation:preliminary'],
                    contradicting_evidence_ids: [],
                    uncertain_evidence_ids: [
                      'observation:preliminary',
                      'observation:estimated',
                      'observation:disputed',
                    ],
                    rationale_rule_ids: ['hypothesis:status_weight:preliminary:+0.250'],
                    statement_type: 'estimate',
                  },
                ],
                scenario_mode: 'material_human_impact',
                recommendation_status: 'unavailable',
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

    expect(
      screen.getByRole('heading', { name: 'Decision evidence and estimates' }),
    ).toBeInTheDocument();
    expect(screen.getByText('Preliminary source observation')).toBeInTheDocument();
    expect(screen.getByText('Source-estimated observation')).toBeInTheDocument();
    expect(screen.getByText('Disputed source observation')).toBeInTheDocument();
    expect(screen.getByText('DM analytical estimate')).toBeInTheDocument();
    expect(screen.getByText('Inferred')).toBeInTheDocument();
    expect(screen.queryByText('Verified source fact')).not.toBeInTheDocument();
  });
});
