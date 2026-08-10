import type { ConversationMessage, ConversationState } from '@/shared/types/assistant';
import {
  copMatchesMultimodalState,
  isCommonOperationalPicture,
  isMultimodalEvidenceState,
} from '@/shared/validation/multimodal';

const STORAGE_KEY = 'disaster-monitor.conversation.v1';

type StorageLike = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

export class SessionConversationStore {
  constructor(
    private readonly storage: StorageLike | null = typeof window === 'undefined'
      ? null
      : window.sessionStorage,
  ) {}

  load(): ConversationState {
    if (!this.storage) {
      return { conversationId: null, messages: [] };
    }

    try {
      const raw = this.storage.getItem(STORAGE_KEY);
      if (!raw) {
        return { conversationId: null, messages: [] };
      }
      const parsed: unknown = JSON.parse(raw);
      if (!this.isConversationState(parsed)) {
        return { conversationId: null, messages: [] };
      }
      return parsed;
    } catch {
      return { conversationId: null, messages: [] };
    }
  }

  save(state: ConversationState): void {
    this.storage?.setItem(STORAGE_KEY, JSON.stringify(state));
  }

  clear(): void {
    this.storage?.removeItem(STORAGE_KEY);
  }

  private isConversationState(value: unknown): value is ConversationState {
    if (!value || typeof value !== 'object') {
      return false;
    }
    const candidate = value as { conversationId?: unknown; messages?: unknown };
    if (
      candidate.conversationId !== null &&
      typeof candidate.conversationId !== 'string'
    ) {
      return false;
    }
    if (!Array.isArray(candidate.messages)) {
      return false;
    }
    return candidate.messages.every((message): message is ConversationMessage => {
      if (!message || typeof message !== 'object') {
        return false;
      }
      const item = message as Record<string, unknown>;
      return (
        typeof item.id === 'string' &&
        (item.role === 'user' || item.role === 'assistant') &&
        typeof item.content === 'string' &&
        this.isStoredReport(item.report)
      );
    });
  }

  private isStoredReport(value: unknown): boolean {
    if (value === undefined) return true;
    if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
    const report = value as Record<string, unknown>;
    if (
      typeof report.responseType !== 'string' ||
      !Array.isArray(report.sources) ||
      !Array.isArray(report.warnings) ||
      !Array.isArray(report.sections) ||
      typeof report.partial !== 'boolean'
    ) {
      return false;
    }
    const multimodal = report.multimodal;
    const cop = report.commonOperationalPicture;
    if (multimodal !== undefined && !isMultimodalEvidenceState(multimodal)) {
      return false;
    }
    if (cop !== undefined && !isCommonOperationalPicture(cop)) return false;
    return (
      cop === undefined ||
      (isMultimodalEvidenceState(multimodal) &&
        copMatchesMultimodalState(cop, multimodal))
    );
  }
}
