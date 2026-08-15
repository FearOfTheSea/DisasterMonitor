import type {
  AssistantRequest,
  AssistantReport,
  AssistantResponse,
  MapView,
} from '@/shared/types/assistant';
import {
  copMatchesMultimodalState,
  isCommonOperationalPicture,
  isMultimodalEvidenceState,
} from '@/shared/validation/multimodal';

export class AssistantApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = 'AssistantApiError';
  }
}

export class AssistantClient {
  constructor(private readonly baseUrl: string) {}

  async ask(
    question: string,
    conversationId: string | null,
    mapView: MapView,
  ): Promise<AssistantResponse> {
    const payload: AssistantRequest = {
      question,
      ...(conversationId ? { conversation_id: conversationId } : {}),
      map_view: {
        center_latitude: mapView.centerLatitude,
        center_longitude: mapView.centerLongitude,
        zoom: mapView.zoom,
      },
    };

    let response: Response;
    try {
      response = await fetch(`${this.baseUrl}/assistant`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
    } catch {
      throw new AssistantApiError(
        'The API could not be reached. Is the local backend running?',
        0,
      );
    }

    const body: unknown = await response.json().catch(() => null);
    if (!response.ok) {
      const detail =
        body && typeof body === 'object' && 'detail' in body
          ? String((body as { detail: unknown }).detail)
          : 'The assistant request failed.';
      throw new AssistantApiError(detail, response.status);
    }

    if (!this.isAssistantResponse(body)) {
      throw new AssistantApiError(
        'The API returned an invalid assistant response.',
        502,
      );
    }
    return body;
  }

  private isAssistantResponse(value: unknown): value is AssistantResponse {
    if (!value || typeof value !== 'object') {
      return false;
    }
    const item = value as Record<string, unknown>;
    if (
      typeof item.message === 'string' &&
      typeof item.conversation_id === 'string' &&
      typeof item.model === 'string'
    ) {
      if (item.response_type !== undefined && typeof item.response_type !== 'string') {
        return false;
      }
      if (item.retrieval_time != null && typeof item.retrieval_time !== 'string') {
        return false;
      }
      if (item.partial !== undefined && typeof item.partial !== 'boolean') {
        return false;
      }
      if (
        item.selected_event !== undefined &&
        item.selected_event !== null &&
        !this.isSelectedEvent(item.selected_event)
      ) {
        return false;
      }
      if (item.warnings !== undefined && !this.isStringArray(item.warnings)) {
        return false;
      }
      if (item.sections !== undefined && !this.isReportSections(item.sections)) {
        return false;
      }
      if (item.sources !== undefined && !this.isSources(item.sources)) {
        return false;
      }
      if (
        item.investigation !== undefined &&
        item.investigation !== null &&
        !this.isInvestigation(item.investigation)
      ) {
        return false;
      }
      if (
        item.decision_support !== undefined &&
        item.decision_support !== null &&
        !this.isDecisionSupport(item.decision_support)
      ) {
        return false;
      }
      const multimodal = item.multimodal;
      const cop = item.common_operational_picture;
      if (
        multimodal !== undefined &&
        multimodal !== null &&
        !isMultimodalEvidenceState(multimodal)
      ) {
        return false;
      }
      if (cop !== undefined && cop !== null && !isCommonOperationalPicture(cop)) {
        return false;
      }
      if (
        cop !== undefined &&
        cop !== null &&
        (!isMultimodalEvidenceState(multimodal) ||
          !copMatchesMultimodalState(cop, multimodal))
      ) {
        return false;
      }
      return true;
    }
    return false;
  }

  private isStringArray(value: unknown): value is string[] {
    return Array.isArray(value) && value.every((item) => typeof item === 'string');
  }

  private isSources(value: unknown): boolean {
    return (
      Array.isArray(value) &&
      value.every((item) => {
        if (!item || typeof item !== 'object') {
          return false;
        }
        const source = item as Record<string, unknown>;
        return (
          typeof source.source_id === 'string' &&
          typeof source.publisher === 'string' &&
          typeof source.title === 'string' &&
          typeof source.canonical_url === 'string' &&
          typeof source.retrieved_at === 'string' &&
          (source.published_at == null || typeof source.published_at === 'string') &&
          (source.updated_at == null || typeof source.updated_at === 'string') &&
          (source.snapshot_id === undefined ||
            source.snapshot_id === null ||
            typeof source.snapshot_id === 'string')
        );
      })
    );
  }

  private isSelectedEvent(value: unknown): boolean {
    if (!value || typeof value !== 'object') {
      return false;
    }
    const item = value as Record<string, unknown>;
    return (
      typeof item.event_id === 'string' &&
      typeof item.hazard === 'string' &&
      typeof item.location === 'string' &&
      typeof item.event_time === 'string' &&
      (item.magnitude == null || typeof item.magnitude === 'number') &&
      (item.intensity == null || typeof item.intensity === 'string') &&
      (item.depth_km == null || typeof item.depth_km === 'number') &&
      (item.provider_ids == null || this.isStringArray(item.provider_ids)) &&
      this.isSources([item.source])
    );
  }

  private isReportSections(value: unknown): boolean {
    return (
      Array.isArray(value) &&
      value.every((item) => {
        if (!item || typeof item !== 'object') {
          return false;
        }
        const section = item as Record<string, unknown>;
        return typeof section.title === 'string' && typeof section.content === 'string';
      })
    );
  }

  private isDecisionSupport(value: unknown): boolean {
    if (!value || typeof value !== 'object') {
      return false;
    }
    const item = value as Record<string, unknown>;
    const sourceTypeByStatus: Record<string, string> = {
      source_backed_event: 'verified_fact',
      confirmed: 'verified_fact',
      preliminary: 'preliminary_observation',
      estimated: 'source_estimate',
      disputed: 'disputed_observation',
    };
    const factsValid =
      Array.isArray(item.facts) &&
      item.facts.every((value) => {
        if (!value || typeof value !== 'object') {
          return false;
        }
        const fact = value as Record<string, unknown>;
        return (
          typeof fact.fact_id === 'string' &&
          typeof fact.statement === 'string' &&
          this.isStringArray(fact.evidence_ids) &&
          this.isStringArray(fact.source_ids) &&
          typeof fact.status === 'string' &&
          fact.statement_type === sourceTypeByStatus[fact.status]
        );
      });
    const estimatesValid =
      Array.isArray(item.estimates) &&
      item.estimates.every((value) => {
        if (!value || typeof value !== 'object') {
          return false;
        }
        const estimate = value as Record<string, unknown>;
        return (
          typeof estimate.estimate_id === 'string' &&
          typeof estimate.proposition === 'string' &&
          typeof estimate.probability === 'number' &&
          estimate.probability >= 0 &&
          estimate.probability <= 1 &&
          this.isStringArray(estimate.supporting_evidence_ids) &&
          this.isStringArray(estimate.contradicting_evidence_ids) &&
          this.isStringArray(estimate.uncertain_evidence_ids) &&
          this.isStringArray(estimate.rationale_rule_ids) &&
          estimate.statement_type === 'estimate'
        );
      });
    return (
      typeof item.artifact_id === 'string' &&
      typeof item.evidence_state_version === 'string' &&
      factsValid &&
      estimatesValid &&
      typeof item.scenario_mode === 'string' &&
      typeof item.recommendation_status === 'string' &&
      item.advisory_only === true
    );
  }

  private isInvestigation(value: unknown): boolean {
    if (!value || typeof value !== 'object') {
      return false;
    }
    const item = value as Record<string, unknown>;
    return (
      typeof item.status === 'string' &&
      typeof item.task_summary === 'string' &&
      (item.hazard == null || typeof item.hazard === 'string') &&
      (item.country == null || typeof item.country === 'string') &&
      this.isStringArray(item.information_needs) &&
      this.isStringArray(item.output_modalities) &&
      this.isStringArray(item.actions) &&
      this.isStringArray(item.source_ids) &&
      typeof item.evidence_count === 'number' &&
      this.isStringArray(item.capability_gaps) &&
      typeof item.termination_reason === 'string' &&
      (item.triage_priority == null || typeof item.triage_priority === 'string') &&
      (item.triage_score == null || typeof item.triage_score === 'number') &&
      (item.triage_action == null || typeof item.triage_action === 'string') &&
      (item.triage_autonomy_mode == null ||
        typeof item.triage_autonomy_mode === 'string') &&
      (item.triage_requires_human_intervention == null ||
        typeof item.triage_requires_human_intervention === 'boolean') &&
      (item.decision_action == null || typeof item.decision_action === 'string') &&
      (item.decision_autonomy_mode == null ||
        typeof item.decision_autonomy_mode === 'string') &&
      (item.decision_requires_human_intervention == null ||
        typeof item.decision_requires_human_intervention === 'boolean') &&
      (item.decision_termination_reason == null ||
        typeof item.decision_termination_reason === 'string') &&
      (item.decision_state_revision == null ||
        typeof item.decision_state_revision === 'number') &&
      (item.decision_active_internal_states == null ||
        this.isStringArray(item.decision_active_internal_states)) &&
      (item.specialist_handoff_count == null ||
        typeof item.specialist_handoff_count === 'number') &&
      (item.specialist_roles == null || this.isStringArray(item.specialist_roles)) &&
      (item.collaboration_status == null ||
        typeof item.collaboration_status === 'string') &&
      (item.collaboration_finding_count == null ||
        typeof item.collaboration_finding_count === 'number') &&
      (item.collaboration_deadlock_count == null ||
        typeof item.collaboration_deadlock_count === 'number') &&
      (item.collaboration_iterations == null ||
        typeof item.collaboration_iterations === 'number') &&
      (item.collaboration_fallback_reason == null ||
        typeof item.collaboration_fallback_reason === 'string') &&
      (item.coordination_supervision_id == null ||
        typeof item.coordination_supervision_id === 'string') &&
      (item.coordination_supervisor_status == null ||
        typeof item.coordination_supervisor_status === 'string') &&
      (item.coordination_sufficient == null ||
        typeof item.coordination_sufficient === 'boolean') &&
      (item.coordination_required_finding_keys == null ||
        this.isStringArray(item.coordination_required_finding_keys)) &&
      (item.coordination_missing_finding_keys == null ||
        this.isStringArray(item.coordination_missing_finding_keys)) &&
      (item.coordination_termination_reason == null ||
        typeof item.coordination_termination_reason === 'string') &&
      (item.coordination_final_rationale == null ||
        typeof item.coordination_final_rationale === 'string') &&
      (item.coordination_evidence_ids == null ||
        this.isStringArray(item.coordination_evidence_ids)) &&
      (item.coordination_analytical_focus == null ||
        typeof item.coordination_analytical_focus === 'string') &&
      (item.coordination_analytical_parameter_set_id == null ||
        typeof item.coordination_analytical_parameter_set_id === 'string') &&
      (item.coordination_analytical_release_id == null ||
        typeof item.coordination_analytical_release_id === 'string')
    );
  }
}

export function toAssistantReport(
  response: AssistantResponse,
): AssistantReport | undefined {
  if (response.response_type !== 'current_disaster') {
    return undefined;
  }
  return {
    responseType: response.response_type,
    selectedEvent: response.selected_event ?? undefined,
    retrievalTime: response.retrieval_time ?? undefined,
    sources: response.sources ?? [],
    warnings: response.warnings ?? [],
    sections: response.sections ?? [],
    partial: response.partial ?? false,
    investigation: response.investigation ?? undefined,
    decisionSupport: response.decision_support ?? undefined,
    multimodal: response.multimodal ?? undefined,
    commonOperationalPicture: response.common_operational_picture ?? undefined,
  };
}
