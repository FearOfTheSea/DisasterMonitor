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
      if (
        item.retrieval_time !== undefined &&
        typeof item.retrieval_time !== 'string'
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
        !this.isInvestigation(item.investigation)
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
          typeof source.retrieved_at === 'string'
        );
      })
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

  private isInvestigation(value: unknown): boolean {
    if (!value || typeof value !== 'object') {
      return false;
    }
    const item = value as Record<string, unknown>;
    return (
      typeof item.status === 'string' &&
      typeof item.task_summary === 'string' &&
      (item.hazard === undefined || typeof item.hazard === 'string') &&
      (item.country === undefined || typeof item.country === 'string') &&
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
      (item.specialist_roles == null || this.isStringArray(item.specialist_roles))
    );
  }
}

export function toAssistantReport(
  response: AssistantResponse,
): AssistantReport | undefined {
  if (!response.response_type || response.response_type === 'assistant') {
    return undefined;
  }
  return {
    responseType: response.response_type,
    selectedEvent: response.selected_event,
    retrievalTime: response.retrieval_time,
    sources: response.sources ?? [],
    warnings: response.warnings ?? [],
    sections: response.sections ?? [],
    partial: response.partial ?? false,
    investigation: response.investigation,
    multimodal: response.multimodal ?? undefined,
    commonOperationalPicture: response.common_operational_picture ?? undefined,
  };
}
