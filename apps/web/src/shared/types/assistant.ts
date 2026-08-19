export type MessageRole = 'user' | 'assistant';

export type ConversationMessage = {
  id: string;
  role: MessageRole;
  content: string;
  mapAction?: MapNavigationAction;
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
  map_action?: MapNavigationAction | null;
  response_type?: string;
  selected_event?: SelectedEvent | null;
  retrieval_time?: string | null;
  sources?: AssistantSource[];
  warnings?: string[];
  sections?: ReportSection[];
  partial?: boolean;
  investigation?: InvestigationSummary | null;
  decision_support?: DecisionSupportArtifact | null;
  multimodal?: MultimodalEvidenceState | null;
  common_operational_picture?: CommonOperationalPicture | null;
  media_gallery?: DisasterMediaGallery | null;
};

export type MapNavigationAction = {
  type: 'fit_bounds';
  bounds: [number, number, number, number];
  label: string;
  max_zoom: number;
};

export type InvestigationSummary = {
  status: string;
  task_summary: string;
  disaster?: string | null;
  country?: string | null;
  information_needs: string[];
  output_modalities: string[];
  actions: string[];
  source_ids: string[];
  evidence_count: number;
  capability_gaps: string[];
  termination_reason: string;
  geographic_scope?: string;
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
  coordination_analytical_release_id?: string | null;
};

export type AssistantSource = {
  source_id: string;
  publisher: string;
  title: string;
  canonical_url: string;
  published_at?: string;
  updated_at?: string;
  retrieved_at: string;
  snapshot_id?: string | null;
};

export type MeasurementKind =
  | 'magnitude'
  | 'intensity'
  | 'depth'
  | 'provider_significance'
  | 'confidence'
  | 'fire_radiative_power'
  | 'severity';

export type EventMeasurement = {
  kind: MeasurementKind;
  value: number | string;
  unit?: string | null;
  source_id: string;
};

export type EventCoordinate = {
  latitude: number;
  longitude: number;
};

export type EventGeometry = {
  kind: 'point' | 'area' | 'track' | 'descriptive';
  coordinates: EventCoordinate[];
  description?: string | null;
  source_id: string;
};

export type SelectedEvent = {
  event_id: string;
  disaster: string;
  location: string;
  event_time: string;
  geometry?: EventGeometry | null;
  measurements: EventMeasurement[];
  source: AssistantSource;
  provider_ids?: string[];
  geography_status: string;
};

export type ReportSection = {
  title: string;
  content: string;
};

export type DecisionFactStatementType =
  | 'verified_fact'
  | 'preliminary_observation'
  | 'source_estimate'
  | 'disputed_observation';

export type DecisionFact = {
  fact_id: string;
  statement: string;
  evidence_ids: string[];
  source_ids: string[];
  status: string;
  statement_type: DecisionFactStatementType;
};

export type DecisionEstimate = {
  estimate_id: string;
  proposition: string;
  probability: number;
  supporting_evidence_ids: string[];
  contradicting_evidence_ids: string[];
  uncertain_evidence_ids: string[];
  rationale_rule_ids: string[];
  statement_type: 'estimate';
};

export type DecisionSupportArtifact = {
  artifact_id: string;
  evidence_state_version: string;
  facts: DecisionFact[];
  estimates: DecisionEstimate[];
  scenario_mode: string;
  recommendation_status: string;
  advisory_only: true;
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
  decisionSupport?: DecisionSupportArtifact;
  multimodal?: MultimodalEvidenceState;
  commonOperationalPicture?: CommonOperationalPicture;
  mediaGallery?: DisasterMediaGallery;
};

export type DisasterMediaItem = {
  media_id: string;
  image_url: string;
  event_id: string;
  physical_event_id: string;
  source_id: string;
  publisher: string;
  source_page_url: string;
  caption: string;
  credit: string;
  credit_kind: 'photographer' | 'agency' | 'publisher';
  published_at: string;
  captured_at?: string | null;
  license_name?: string | null;
  license_url?: string | null;
  rights_status: 'licensed_reuse' | 'source_preview';
  role:
    | 'aftermath'
    | 'rescue_effort'
    | 'relief_operation'
    | 'scientific_overview'
    | 'relevant_scene';
  association_status: 'exact_event_link' | 'corroborated';
  association_rule_ids: string[];
  association_detail: string;
  uncertainty: string;
  content_sha256: string;
  width: number;
  height: number;
};

export type DisasterMediaGallery = {
  event_id: string;
  physical_event_id: string;
  generated_at: string;
  items: DisasterMediaItem[];
  rejected_count: number;
  provider_ids: string[];
  warnings: string[];
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
  declared_disaster?: string | null;
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
  disaster_match?: boolean | null;
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
