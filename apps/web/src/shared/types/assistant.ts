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
  multimodal?: MultimodalEvidenceState | null;
  common_operational_picture?: CommonOperationalPicture | null;
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
  triage_priority?: string | null;
  triage_score?: number | null;
  triage_action?: string | null;
  triage_autonomy_mode?: string | null;
  triage_requires_human_intervention?: boolean | null;
  decision_action?: string | null;
  decision_autonomy_mode?: string | null;
  decision_requires_human_intervention?: boolean | null;
  decision_termination_reason?: string | null;
  decision_state_revision?: number | null;
  decision_active_internal_states?: string[];
  specialist_handoff_count?: number;
  specialist_roles?: string[];
  collaboration_status?: string | null;
  collaboration_finding_count?: number;
  collaboration_deadlock_count?: number;
  collaboration_iterations?: number | null;
  collaboration_fallback_reason?: string | null;
  coordination_supervision_id?: string | null;
  coordination_supervisor_status?: string | null;
  coordination_sufficient?: boolean | null;
  coordination_required_finding_keys?: string[];
  coordination_missing_finding_keys?: string[];
  coordination_termination_reason?: string | null;
  coordination_final_rationale?: string | null;
  coordination_evidence_ids?: string[];
  coordination_analytical_focus?: string | null;
  coordination_analytical_parameter_set_id?: string | null;
};

export type AssistantSource = {
  source_id: string;
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
  multimodal?: MultimodalEvidenceState;
  commonOperationalPicture?: CommonOperationalPicture;
};

export type Wgs84PointGeometry = {
  type: 'Point';
  coordinates: [number, number];
  crs: 'EPSG:4326';
};

export type Wgs84LineStringGeometry = {
  type: 'LineString';
  coordinates: [number, number][];
  crs: 'EPSG:4326';
};

export type Wgs84PolygonGeometry = {
  type: 'Polygon';
  coordinates: [number, number][][];
  crs: 'EPSG:4326';
};

export type CopGeometry =
  Wgs84PointGeometry | Wgs84LineStringGeometry | Wgs84PolygonGeometry;

export type MultimodalSource = {
  source_id: string;
  attribution: string;
  canonical_url?: string | null;
  dataset_id?: string | null;
  license_name?: string | null;
};

export type MultimodalAsset = {
  asset_id: string;
  source: MultimodalSource;
  retrieved_at: string;
  captured_at?: string | null;
  modality: string;
  media_type: string;
  content_sha256: string;
  byte_length: number;
  width?: number | null;
  height?: number | null;
  footprint?: Wgs84PolygonGeometry | null;
  declared_hazard?: string | null;
  declared_country_code?: string | null;
  capture_role: string;
  processing_level?: string | null;
  parent_asset_ids: string[];
  event_id_hint?: string | null;
  eligibility: string;
  eligibility_reasons: string[];
};

export type AssetEventAssociation = {
  association_id: string;
  asset_id: string;
  physical_event_id: string;
  status: string;
  geography_match?: boolean | null;
  time_match?: boolean | null;
  hazard_match?: boolean | null;
  country_match?: boolean | null;
  event_id_match?: boolean | null;
  distance_km?: number | null;
  time_delta_seconds?: number | null;
  rule_ids: string[];
  detail: string;
};

export type VisualAnalysisConfiguration = {
  model_id: string;
  model_digest?: string | null;
  adapter_version: string;
  analysis_version: string;
  prompt_version: string;
  preprocessing_version: string;
  maximum_output_tokens: number;
  temperature: number;
  seed: number;
};

export type VisualObservation = {
  observation_id: string;
  asset_id: string;
  association_id: string;
  physical_event_id: string;
  modality: 'image';
  truth_status: 'analytical';
  kind: string;
  status: string;
  damage_level?: string | null;
  question?: string | null;
  answer?: string | null;
  answerable?: boolean | null;
  confidence?: number | null;
  uncertainty: string;
  visual_cues: string[];
  configuration: VisualAnalysisConfiguration;
  created_at: string;
  safety_rule_ids: string[];
};

export type MultimodalEvidenceState = {
  state_version: string;
  evidence_world_state_version: string;
  physical_event_id: string;
  assets: MultimodalAsset[];
  associations: AssetEventAssociation[];
  observations: VisualObservation[];
  evaluated_at: string;
};

type CopFeatureBase = {
  feature_id: string;
  physical_event_id: string;
  source_asset_ids: string[];
  created_at: string;
  updated_at?: string | null;
  semantic_kind: string;
  geometry: CopGeometry;
  attribution: string;
  status: string;
  uncertainty: string;
};

export type SourceMapFeature = CopFeatureBase & {
  feature_type: 'source';
  source_id: string;
  authority: 'official_source' | 'source_supplied';
  source_authority: 'official' | 'source_supplied';
};

export type AnalyticalMapFeature = CopFeatureBase & {
  feature_type: 'analytical';
  visual_observation_ids: string[];
  confidence?: number | null;
  authority: 'analytical_generated';
};

export type SourceMapLayer = {
  layer_type: 'source';
  layer_id: string;
  physical_event_id: string;
  title: string;
  semantic_kind: string;
  features: SourceMapFeature[];
  source_ids: string[];
  source_asset_ids: string[];
  created_at: string;
  updated_at: string;
  status: string;
  uncertainty: string;
  attribution: string;
};

export type AnalyticalMapLayer = {
  layer_type: 'analytical';
  layer_id: string;
  physical_event_id: string;
  title: string;
  semantic_kind: string;
  features: AnalyticalMapFeature[];
  source_asset_ids: string[];
  visual_observation_ids: string[];
  created_at: string;
  updated_at: string;
  status: string;
  uncertainty: string;
  attribution: string;
};

export type CopLayer = SourceMapLayer | AnalyticalMapLayer;

export type CommonOperationalPicture = {
  cop_id: string;
  physical_event_id: string;
  multimodal_state_version: string;
  created_at: string;
  updated_at: string;
  status: string;
  layers: CopLayer[];
};

export type ConversationState = {
  conversationId: string | null;
  messages: ConversationMessage[];
};

export type ConversationStatus = 'idle' | 'loading' | 'error';
