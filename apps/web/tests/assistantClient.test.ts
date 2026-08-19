import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  AssistantApiError,
  AssistantClient,
  toAssistantReport,
} from '@/features/assistant/api/assistantClient';
import { commonOperationalPicture, multimodalState } from './fixtures/multimodal';

describe('AssistantClient', () => {
  afterEach(() => vi.restoreAllMocks());

  it('posts the typed question and current map view', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          message: 'Use the map to inspect the area.',
          conversation_id: 'session-1',
          model: 'fake-qwen',
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    );
    const client = new AssistantClient('http://localhost:8001/api/v1');

    await expect(
      client.ask('What is visible?', null, {
        centerLatitude: 21.03,
        centerLongitude: 105.85,
        zoom: 10,
      }),
    ).resolves.toMatchObject({ model: 'fake-qwen' });
    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8001/api/v1/assistant',
      expect.objectContaining({
        method: 'POST',
        body: expect.stringContaining('center_latitude'),
      }),
    );
  });

  it('translates an API error into a stable client error', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ detail: 'The local model is unavailable.' }), {
        status: 503,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    const client = new AssistantClient('http://localhost:8001/api/v1');

    await expect(
      client.ask('Will it flood?', null, {
        centerLatitude: 21,
        centerLongitude: 105,
        zoom: 8,
      }),
    ).rejects.toEqual(
      expect.objectContaining<Partial<AssistantApiError>>({ status: 503 }),
    );
  });

  it('accepts a validated viewport action from the assistant', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          message: 'Showing Japan on the map.',
          conversation_id: 'session-map',
          model: 'fake-qwen',
          map_action: {
            type: 'fit_bounds',
            bounds: [122, 20, 154, 46],
            label: 'Japan',
            max_zoom: 10,
          },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    );
    const client = new AssistantClient('http://localhost:8001/api/v1');

    await expect(
      client.ask('Zoom into Japan.', null, {
        centerLatitude: 21.03,
        centerLongitude: 105.85,
        zoom: 10,
      }),
    ).resolves.toMatchObject({
      map_action: { type: 'fit_bounds', label: 'Japan' },
    });
  });

  it('rejects arbitrary or malformed assistant UI actions', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          message: 'Unsafe action',
          conversation_id: 'session-map',
          model: 'fake-qwen',
          map_action: {
            type: 'run_javascript',
            code: 'arbitrary()',
          },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    );
    const client = new AssistantClient('http://localhost:8001/api/v1');

    await expect(
      client.ask('Move the map.', null, {
        centerLatitude: 21.03,
        centerLongitude: 105.85,
        zoom: 10,
      }),
    ).rejects.toEqual(
      expect.objectContaining<Partial<AssistantApiError>>({ status: 502 }),
    );
  });

  it('accepts structured current-disaster metadata and source timestamps', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          message: '## Situation summary',
          conversation_id: 'session-1',
          model: 'source-backed-report',
          response_type: 'current_disaster',
          selected_event: {
            event_id: 'global-catalog:fixture-event',
            disaster: 'earthquake',
            location: 'Ishikawa, Japan',
            event_time: '2026-08-05T11:00:00Z',
            geometry: {
              kind: 'point',
              coordinates: [{ latitude: 37, longitude: 137 }],
              description: null,
              source_id: 'global-catalog-rolling-earthquakes',
            },
            measurements: [],
            geography_status: 'in_country',
            source: {
              source_id: 'global-catalog-rolling-earthquakes',
              publisher: 'Global Catalog',
              title: 'Fixture event',
              canonical_url: 'https://example.test/event',
              retrieved_at: '2026-08-05T12:00:00Z',
            },
          },
          retrieval_time: '2026-08-05T12:00:00Z',
          sources: [
            {
              source_id: 'global-catalog-rolling-earthquakes',
              publisher: 'Global Catalog',
              title: 'Fixture event',
              canonical_url: 'https://example.test/event',
              published_at: '2026-08-05T11:00:00Z',
              retrieved_at: '2026-08-05T12:00:00Z',
            },
          ],
          sections: [{ title: 'Situation summary', content: 'Verified.' }],
          warnings: ['One source is unavailable.'],
          partial: true,
          investigation: {
            status: 'partial',
            task_summary: 'Latest earthquake damage?',
            disaster: 'earthquake',
            country: 'JPN',
            information_needs: ['physical_damage'],
            output_modalities: ['text'],
            actions: ['Selected the source-backed event global-catalog:fixture.'],
            source_ids: ['global-catalog-rolling-earthquakes'],
            evidence_count: 1,
            capability_gaps: [],
            termination_reason: 'partial_evidence',
            triage_priority: 'high',
            triage_score: 55,
            triage_action: 'request_priority_review',
            triage_autonomy_mode: 'human_on_the_loop',
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
            coordination_required_finding_keys: ['event_identity', 'decision_policy'],
            coordination_missing_finding_keys: [],
            coordination_termination_reason: 'sufficient_analytical_end_state',
            coordination_final_rationale: 'The bounded checklist is complete.',
            coordination_evidence_ids: ['physical-event:fixture'],
            coordination_analytical_focus: 'material_conflicts',
            coordination_analytical_parameter_set_id: 'analytical-tuning:v3-governed',
            coordination_analytical_release_id: 'analytical-tuning-release:v3-governed',
          },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    );
    const client = new AssistantClient('http://localhost:8001/api/v1');

    await expect(
      client.ask('Latest earthquake damage?', null, {
        centerLatitude: 21,
        centerLongitude: 105,
        zoom: 8,
      }),
    ).resolves.toMatchObject({
      response_type: 'current_disaster',
      partial: true,
      selected_event: {
        geometry: {
          kind: 'point',
          coordinates: [{ latitude: 37, longitude: 137 }],
        },
      },
      investigation: { status: 'partial' },
    });
  });

  it('accepts only provenance-complete media associated to the selected event', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          message: 'Source-backed event with photos.',
          conversation_id: 'session-media',
          model: 'source-backed-agent',
          response_type: 'current_disaster',
          selected_event: {
            event_id: 'us6000tjl2',
            disaster: 'earthquake',
            location: 'San José del Palmar, Colombia',
            event_time: '2026-08-10T05:54:00Z',
            geometry: null,
            measurements: [],
            geography_status: 'in_country',
            source: {
              source_id: 'usgs-earthquakes',
              publisher: 'USGS',
              title: 'M 7.4 event',
              canonical_url: 'https://earthquake.usgs.gov/event',
              retrieved_at: '2026-08-15T12:00:00Z',
            },
          },
          media_gallery: {
            event_id: 'us6000tjl2',
            physical_event_id: 'physical-event:colombia',
            generated_at: '2026-08-15T12:00:00Z',
            rejected_count: 1,
            provider_ids: ['bounded-news-event-media-v1'],
            warnings: [],
            items: [
              {
                media_id: `media:${'a'.repeat(32)}`,
                image_url: `http://localhost:8001/api/v1/media/media:${'a'.repeat(32)}`,
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
                  'media.association.disaster_text',
                  'media.association.country_text',
                ],
                association_detail: 'Source metadata agrees with the event.',
                uncertainty: 'Source-associated preview, not a verified fact.',
                content_sha256: 'b'.repeat(64),
                width: 1200,
                height: 675,
              },
            ],
          },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    );
    const client = new AssistantClient('http://localhost:8001/api/v1');

    const response = await client.ask('Latest Colombia earthquake?', null, {
      centerLatitude: 5,
      centerLongitude: -76,
      zoom: 7,
    });

    expect(response.media_gallery?.items).toHaveLength(1);
    expect(toAssistantReport(response)?.mediaGallery?.rejected_count).toBe(1);
  });

  it('rejects media that the API labels as event-unmatched', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          message: 'Unsafe media response.',
          conversation_id: 'session-media',
          model: 'source-backed-agent',
          response_type: 'current_disaster',
          media_gallery: {
            event_id: 'selected-event',
            physical_event_id: 'physical-event:selected',
            generated_at: '2026-08-15T12:00:00Z',
            rejected_count: 0,
            provider_ids: [],
            warnings: [],
            items: [
              {
                media_id: `media:${'a'.repeat(32)}`,
                image_url: 'http://localhost:8001/api/v1/media/unsafe',
                event_id: 'selected-event',
                physical_event_id: 'physical-event:selected',
                source_id: 'source',
                publisher: 'Publisher',
                source_page_url: 'https://example.test/article',
                caption: 'Old unrelated image',
                credit: 'Publisher',
                credit_kind: 'publisher',
                published_at: '2026-08-15T12:00:00Z',
                rights_status: 'source_preview',
                role: 'relevant_scene',
                association_status: 'rejected',
                association_rule_ids: ['media.association.explicit_year_mismatch'],
                association_detail: 'Rejected.',
                uncertainty: 'Unmatched.',
                content_sha256: 'b'.repeat(64),
                width: 1200,
                height: 675,
              },
            ],
          },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    );
    const client = new AssistantClient('http://localhost:8001/api/v1');

    await expect(
      client.ask('Show the earthquake.', null, {
        centerLatitude: 0,
        centerLongitude: 0,
        zoom: 2,
      }),
    ).rejects.toMatchObject({ status: 502 });
  });

  it('accepts nullable optional fields in a clarification response', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          message:
            'This phase can investigate exactly one country at a time. Which country should I use?',
          conversation_id: 'session-clarification',
          model: 'disaster-agent',
          response_type: 'current_disaster_clarification',
          selected_event: null,
          retrieval_time: null,
          sources: [],
          warnings: [],
          sections: [],
          partial: true,
          investigation: {
            status: 'clarification_required',
            task_summary: 'Which country should I use?',
            disaster: 'earthquake',
            country: null,
            information_needs: ['event_overview'],
            output_modalities: ['text'],
            actions: [],
            source_ids: [],
            evidence_count: 0,
            capability_gaps: ['Which country should I use?'],
            termination_reason: 'clarification_required',
            triage_priority: null,
            triage_score: null,
            triage_action: null,
            triage_autonomy_mode: null,
            triage_requires_human_intervention: null,
            decision_action: null,
            decision_autonomy_mode: null,
            decision_requires_human_intervention: null,
            decision_termination_reason: null,
            decision_state_revision: null,
            decision_active_internal_states: [],
            specialist_handoff_count: 0,
            specialist_roles: [],
            collaboration_status: null,
            collaboration_finding_count: 0,
            collaboration_deadlock_count: 0,
            collaboration_iterations: null,
            collaboration_fallback_reason: null,
            coordination_supervision_id: null,
            coordination_supervisor_status: null,
            coordination_sufficient: null,
            coordination_required_finding_keys: [],
            coordination_missing_finding_keys: [],
            coordination_termination_reason: null,
            coordination_final_rationale: null,
            coordination_evidence_ids: [],
            coordination_analytical_focus: null,
            coordination_analytical_parameter_set_id: null,
            coordination_analytical_release_id: null,
          },
          decision_support: null,
          multimodal: null,
          common_operational_picture: null,
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    );
    const client = new AssistantClient('http://localhost:8001/api/v1');

    const response = await client.ask(
      'Compare the latest earthquakes in Japan and Venezuela.',
      null,
      {
        centerLatitude: 20,
        centerLongitude: 0,
        zoom: 2,
      },
    );

    expect(response).toMatchObject({
      response_type: 'current_disaster_clarification',
      selected_event: null,
      retrieval_time: null,
      investigation: { country: null },
    });
    expect(toAssistantReport(response)).toBeUndefined();
  });

  it('rejects investigation metadata containing an invalid action shape', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          message: 'Unsafe shape',
          conversation_id: 'session-1',
          model: 'source-backed-agent',
          investigation: {
            status: 'completed',
            task_summary: 'task',
            information_needs: [],
            output_modalities: [],
            actions: [{ reasoning: 'hidden' }],
            source_ids: [],
            evidence_count: 0,
            capability_gaps: [],
            termination_reason: 'done',
          },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    );
    const client = new AssistantClient('http://localhost:8001/api/v1');

    await expect(
      client.ask('Latest earthquake?', null, {
        centerLatitude: 21,
        centerLongitude: 105,
        zoom: 8,
      }),
    ).rejects.toMatchObject({ status: 502 });
  });

  it('rejects invalid triage authority metadata', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          message: 'Invalid triage shape',
          conversation_id: 'session-1',
          model: 'source-backed-agent',
          response_type: 'current_disaster',
          investigation: {
            status: 'completed',
            task_summary: 'task',
            information_needs: [],
            output_modalities: [],
            actions: [],
            source_ids: [],
            evidence_count: 0,
            capability_gaps: [],
            termination_reason: 'done',
            triage_requires_human_intervention: 'no',
          },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    );
    const client = new AssistantClient('http://localhost:8001/api/v1');

    await expect(
      client.ask('Latest earthquake?', null, {
        centerLatitude: 21,
        centerLongitude: 105,
        zoom: 8,
      }),
    ).rejects.toMatchObject({ status: 502 });
  });

  it('rejects invalid bounded-decision state metadata', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          message: 'Invalid decision state',
          conversation_id: 'session-1',
          model: 'source-backed-agent',
          response_type: 'current_disaster',
          investigation: {
            status: 'completed',
            task_summary: 'task',
            information_needs: [],
            output_modalities: [],
            actions: [],
            source_ids: [],
            evidence_count: 0,
            capability_gaps: [],
            termination_reason: 'done',
            decision_active_internal_states: ['monitoring_active', { unsafe: true }],
          },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    );
    const client = new AssistantClient('http://localhost:8001/api/v1');

    await expect(
      client.ask('Latest earthquake?', null, {
        centerLatitude: 21,
        centerLongitude: 105,
        zoom: 8,
      }),
    ).rejects.toMatchObject({ status: 502 });
  });

  it('accepts decision evidence without promoting uncertain source status', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          message: 'Bounded decision support.',
          conversation_id: 'session-ds',
          model: 'source-backed-agent',
          response_type: 'current_disaster',
          decision_support: {
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
            ],
            estimates: [
              {
                estimate_id: 'decision-estimate:fixture',
                proposition: 'Material human impact is likely.',
                probability: 0.75,
                supporting_evidence_ids: ['observation:preliminary'],
                contradicting_evidence_ids: [],
                uncertain_evidence_ids: ['observation:preliminary'],
                rationale_rule_ids: ['hypothesis:status_weight:preliminary:+0.250'],
                statement_type: 'estimate',
              },
            ],
            scenario_mode: 'material_human_impact',
            recommendation_status: 'unavailable',
            advisory_only: true,
          },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    );
    const client = new AssistantClient('http://localhost:8001/api/v1');

    await expect(
      client.ask('What decisions are supported?', null, {
        centerLatitude: 21,
        centerLongitude: 105,
        zoom: 8,
      }),
    ).resolves.toMatchObject({
      decision_support: {
        facts: [{ statement_type: 'preliminary_observation' }],
        estimates: [{ statement_type: 'estimate' }],
      },
    });
  });

  it('rejects a preliminary source observation relabeled as verified fact', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          message: 'Unsafe epistemic promotion.',
          conversation_id: 'session-ds',
          model: 'source-backed-agent',
          decision_support: {
            artifact_id: 'decision-support:fixture',
            evidence_state_version: 'evidence-state:fixture',
            facts: [
              {
                fact_id: 'decision-fact:preliminary',
                statement: 'Injuries are preliminarily reported.',
                evidence_ids: ['observation:preliminary'],
                source_ids: ['source:fixture'],
                status: 'preliminary',
                statement_type: 'verified_fact',
              },
            ],
            estimates: [],
            scenario_mode: 'insufficient_evidence',
            recommendation_status: 'unavailable',
            advisory_only: true,
          },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    );
    const client = new AssistantClient('http://localhost:8001/api/v1');

    await expect(
      client.ask('What decisions are supported?', null, {
        centerLatitude: 21,
        centerLongitude: 105,
        zoom: 8,
      }),
    ).rejects.toMatchObject({ status: 502 });
  });

  it('accepts provenance-complete multimodal state and its typed COP', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          message: 'Analytical imagery result.',
          conversation_id: 'session-mm',
          model: 'source-backed-agent',
          response_type: 'current_disaster',
          multimodal: multimodalState,
          common_operational_picture: commonOperationalPicture,
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    );
    const client = new AssistantClient('http://localhost:8001/api/v1');

    await expect(
      client.ask('Analyze the supplied image.', null, {
        centerLatitude: 35,
        centerLongitude: 137,
        zoom: 8,
      }),
    ).resolves.toMatchObject({
      multimodal: { state_version: 'multimodal-state:fixture' },
      common_operational_picture: { status: 'current' },
    });
  });

  it('rejects a COP whose provenance is absent from multimodal state', async () => {
    const unsafe = structuredClone(commonOperationalPicture);
    unsafe.layers[0].features[0].source_asset_ids = ['asset:not-admitted'];
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          message: 'Unsafe analytical result.',
          conversation_id: 'session-mm',
          model: 'source-backed-agent',
          multimodal: multimodalState,
          common_operational_picture: unsafe,
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    );
    const client = new AssistantClient('http://localhost:8001/api/v1');

    await expect(
      client.ask('Analyze the supplied image.', null, {
        centerLatitude: 35,
        centerLongitude: 137,
        zoom: 8,
      }),
    ).rejects.toMatchObject({ status: 502 });
  });
});
