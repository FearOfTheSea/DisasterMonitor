export type MessageRole = 'user' | 'assistant';

export type ConversationMessage = {
  id: string;
  role: MessageRole;
  content: string;
  report?: AssistantReport;
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
  response_type?: string;
  selected_event?: SelectedEvent;
  retrieval_time?: string;
  sources?: AssistantSource[];
  warnings?: string[];
  sections?: ReportSection[];
  partial?: boolean;
  investigation?: InvestigationSummary;
};

export type InvestigationSummary = {
  status: string;
  task_summary: string;
  hazard?: string;
  country?: string;
  information_needs: string[];
  output_modalities: string[];
  actions: string[];
  source_ids: string[];
  evidence_count: number;
  capability_gaps: string[];
  termination_reason: string;
};

export type AssistantSource = {
  publisher: string;
  title: string;
  canonical_url: string;
  published_at?: string;
  updated_at?: string;
  retrieved_at: string;
};

export type SelectedEvent = {
  event_id: string;
  hazard: string;
  location: string;
  event_time: string;
  magnitude?: number;
  intensity?: string;
  depth_km?: number;
  source: AssistantSource;
  provider_ids?: string[];
};

export type ReportSection = {
  title: string;
  content: string;
};

export type AssistantReport = {
  responseType: string;
  selectedEvent?: SelectedEvent;
  retrievalTime?: string;
  sources: AssistantSource[];
  warnings: string[];
  sections: ReportSection[];
  partial: boolean;
  investigation?: InvestigationSummary;
};

export type ConversationState = {
  conversationId: string | null;
  messages: ConversationMessage[];
};

export type ConversationStatus = 'idle' | 'loading' | 'error';
