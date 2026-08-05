import type {
  AssistantRequest,
  AssistantResponse,
  MapView,
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
    return (
      typeof item.message === 'string' &&
      typeof item.conversation_id === 'string' &&
      typeof item.model === 'string'
    );
  }
}
