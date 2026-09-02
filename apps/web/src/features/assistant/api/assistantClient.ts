import {
  validatedAssistantResponse,
  validatedConversation,
  validatedConversationSummaries,
} from '@/features/assistant/api/assistantResponseValidation';
import type {
  AssistantReport,
  AssistantRequest,
  AssistantResponse,
  ConversationSummary,
  MapView,
  PersistedConversation,
} from '@/shared/types/assistant';

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
      throw unreachableApiError();
    }

    const body: unknown = await response.json().catch(() => null);
    if (!response.ok) {
      throw responseError(body, response.status, 'The assistant request failed.');
    }
    const validated = validatedAssistantResponse(body);
    if (!validated) {
      throw new AssistantApiError(
        'The API returned an invalid assistant response.',
        502,
      );
    }
    return validated;
  }

  async listConversations(): Promise<ConversationSummary[]> {
    const body = await this.request('/conversations', 'GET', 'conversation list');
    const validated = validatedConversationSummaries(body);
    if (!validated) {
      throw new AssistantApiError(
        'The API returned an invalid conversation list.',
        502,
      );
    }
    return validated;
  }

  async getConversation(conversationId: string): Promise<PersistedConversation> {
    const body = await this.request(
      `/conversations/${encodeURIComponent(conversationId)}`,
      'GET',
      'conversation',
    );
    const validated = validatedConversation(body);
    if (!validated) {
      throw new AssistantApiError('The API returned an invalid conversation.', 502);
    }
    return validated;
  }

  async deleteConversation(conversationId: string): Promise<void> {
    await this.request(
      `/conversations/${encodeURIComponent(conversationId)}`,
      'DELETE',
      'conversation deletion',
    );
  }

  private async request(
    path: string,
    method: 'GET' | 'DELETE',
    resource: string,
  ): Promise<unknown> {
    let response: Response;
    try {
      response = await fetch(`${this.baseUrl}${path}`, {
        method,
        headers: method === 'GET' ? undefined : { 'Content-Type': 'application/json' },
      });
    } catch {
      throw unreachableApiError();
    }

    if (response.status === 204) return undefined;
    const body: unknown = await response.json().catch(() => null);
    if (!response.ok) {
      throw responseError(body, response.status, `The ${resource} request failed.`);
    }
    return body;
  }
}

function unreachableApiError(): AssistantApiError {
  return new AssistantApiError(
    'The API could not be reached. Is the local backend running?',
    0,
  );
}

function responseError(
  body: unknown,
  status: number,
  fallback: string,
): AssistantApiError {
  const detail =
    body && typeof body === 'object' && 'detail' in body
      ? String((body as { detail: unknown }).detail)
      : fallback;
  return new AssistantApiError(detail, status);
}

export function toAssistantReport(
  response: AssistantResponse,
): AssistantReport | undefined {
  if (
    !response.response_type?.startsWith('current_disaster') ||
    (!response.investigation_case &&
      !response.selected_event &&
      !(response.sections?.length || 0))
  ) {
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
    investigationCase: response.investigation_case ?? undefined,
    decisionSupport: response.decision_support ?? undefined,
    multimodal: response.multimodal ?? undefined,
    commonOperationalPicture: response.common_operational_picture ?? undefined,
    mediaGallery: response.media_gallery ?? undefined,
  };
}
