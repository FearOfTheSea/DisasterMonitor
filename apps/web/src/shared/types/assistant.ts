export type MessageRole = 'user' | 'assistant';

export type ConversationMessage = {
  id: string;
  role: MessageRole;
  content: string;
};

export type MapView = {
  centerLatitude: number;
  centerLongitude: number;
  zoom: number;
};

export type AssistantRequest = {
  question: string;
  conversation_id?: string;
  map_view?: {
    center_latitude: number;
    center_longitude: number;
    zoom: number;
  };
};

export type AssistantResponse = {
  message: string;
  conversation_id: string;
  model: string;
};

export type ConversationState = {
  conversationId: string | null;
  messages: ConversationMessage[];
};

export type ConversationStatus = 'idle' | 'loading' | 'error';
