// Generated from the DisasterMonitor backend OpenAPI schema.
// Run `npm run generate:api-contract` after backend schema changes.

export type ActiveIncidentResponse = {
  disaster: Disaster;
  event_id: string;
  event_time: string;
  geometry?: EventGeometryResponse | null;
  location: string;
  measurements?: Array<EventMeasurementResponse>;
  provider_ids?: Array<string>;
  provider_tier: ProviderTier;
  source: SourceResponse;
  source_authority: SourceAuthority;
};

export type ActiveIncidentsSnapshotResponse = {
  coverage?: Array<DisasterIncidentCoverageResponse>;
  incidents?: Array<ActiveIncidentResponse>;
  retrieved_at: string;
  warnings?: Array<string>;
};

export type AnalyticalMapFeatureResponse = {
  attribution: string;
  authority: 'analytical_generated';
  confidence?: number | null;
  created_at: string;
  feature_id: string;
  feature_type: 'analytical';
  geometry:
    PointGeometryResponse | LineStringGeometryResponse | PolygonGeometryResponse;
  physical_event_id: string;
  semantic_kind: string;
  source_asset_ids: Array<string>;
  status: string;
  uncertainty: string;
  updated_at?: string | null;
  visual_observation_ids: Array<string>;
};

export type AnalyticalMapLayerResponse = {
  attribution: string;
  created_at: string;
  features: Array<AnalyticalMapFeatureResponse>;
  layer_id: string;
  layer_type: 'analytical';
  physical_event_id: string;
  semantic_kind: string;
  source_asset_ids: Array<string>;
  status: string;
  title: string;
  uncertainty: string;
  updated_at: string;
  visual_observation_ids: Array<string>;
};

export type AssetEventAssociationResponse = {
  asset_id: string;
  association_id: string;
  country_match?: boolean | null;
  detail: string;
  disaster_match?: boolean | null;
  distance_km?: number | null;
  event_id_match?: boolean | null;
  geography_match?: boolean | null;
  physical_event_id: string;
  rule_ids?: Array<string>;
  status: string;
  time_delta_seconds?: number | null;
  time_match?: boolean | null;
};

export type AssistantRequest = {
  conversation_id?: string | null;
  map_view?: MapViewRequest | null;
  multimodal_assets?: Array<MultimodalAssetRequest>;
  question: string;
};

export type AssistantResponse = {
  common_operational_picture?: CommonOperationalPictureResponse | null;
  conversation_id: string;
  decision_support?: DecisionSupportResponse | null;
  investigation?: InvestigationResponse | null;
  map_action?: MapNavigationActionResponse | null;
  media_gallery?: DisasterMediaGalleryResponse | null;
  message: string;
  model: string;
  multimodal?: MultimodalStateResponse | null;
  partial?: boolean;
  response_type?: string;
  retrieval_time?: string | null;
  sections?: Array<ReportSectionResponse>;
  selected_event?: SelectedEventResponse | null;
  sources?: Array<SourceResponse>;
  warnings?: Array<string>;
};

export type CaptureRole = 'pre_event' | 'post_event' | 'single_capture' | 'unknown';

export type CommonOperationalPictureResponse = {
  cop_id: string;
  created_at: string;
  layers: Array<SourceMapLayerResponse | AnalyticalMapLayerResponse>;
  multimodal_state_version: string;
  physical_event_id: string;
  status: string;
  updated_at: string;
};

export type ConversationMessageResponse = {
  assistant_response?: AssistantResponse | null;
  content: string;
  created_at: string;
  id: string;
  role: 'user' | 'assistant';
};

export type ConversationResponse = {
  conversation_id: string;
  created_at: string;
  messages?: Array<ConversationMessageResponse>;
  updated_at: string;
};

export type ConversationSummaryResponse = {
  conversation_id: string;
  created_at: string;
  preview: string;
  updated_at: string;
};

export type CountryCatalogSourceResponse = {
  revision: string;
  sha256: string;
  source_id: string;
  version: string;
};

export type CountryCatalogUpdateResponse = {
  active_version: string;
  automatic_updates_enabled: boolean;
  country_count: number;
  failure_code?: string | null;
  last_attempt_at?: string | null;
  last_success_at?: string | null;
  message: string;
  next_scheduled_at?: string | null;
  sources?: Array<CountryCatalogSourceResponse>;
  state: 'never_run' | 'running' | 'updated' | 'unchanged' | 'failed';
  trigger?: 'manual' | 'scheduled' | 'script' | null;
};

export type DecisionEstimateResponse = {
  contradicting_evidence_ids: Array<string>;
  estimate_id: string;
  probability: number;
  proposition: string;
  rationale_rule_ids: Array<string>;
  statement_type: string;
  supporting_evidence_ids: Array<string>;
  uncertain_evidence_ids: Array<string>;
};

export type DecisionFactResponse = {
  evidence_ids: Array<string>;
  fact_id: string;
  source_ids: Array<string>;
  statement: string;
  statement_type: string;
  status: string;
};

export type DecisionSupportResponse = {
  advisory_only: boolean;
  artifact_id: string;
  estimates: Array<DecisionEstimateResponse>;
  evidence_state_version: string;
  facts: Array<DecisionFactResponse>;
  recommendation_status: string;
  scenario_mode: string;
};

export type Disaster =
  | 'earthquake'
  | 'flood'
  | 'wildfire'
  | 'landslide'
  | 'tropical_cyclone'
  | 'volcanic_eruption';

export type DisasterIncidentCoverageResponse = {
  detail: string;
  disaster: Disaster;
  incident_count: number;
  providers?: Array<string>;
  state: 'events_found' | 'no_matching_records' | 'degraded' | 'unavailable';
};

export type DisasterMediaGalleryResponse = {
  event_id: string;
  generated_at: string;
  items?: Array<DisasterMediaItemResponse>;
  physical_event_id: string;
  provider_ids?: Array<string>;
  rejected_count?: number;
  warnings?: Array<string>;
};

export type DisasterMediaItemResponse = {
  association_detail: string;
  association_rule_ids?: Array<string>;
  association_status: string;
  caption: string;
  captured_at?: string | null;
  content_sha256: string;
  credit: string;
  credit_kind: string;
  event_id: string;
  height: number;
  image_url: string;
  license_name?: string | null;
  license_url?: string | null;
  media_id: string;
  physical_event_id: string;
  published_at: string;
  publisher: string;
  rights_status: string;
  role: string;
  source_id: string;
  source_page_url: string;
  uncertainty: string;
  width: number;
};

export type EventCoordinateResponse = {
  latitude: number;
  longitude: number;
};

export type EventGeometryResponse = {
  coordinates?: Array<EventCoordinateResponse>;
  description?: string | null;
  estimated?: boolean;
  kind: 'point' | 'area' | 'track' | 'descriptive';
  source_id: string;
};

export type EventMeasurementResponse = {
  kind: MeasurementKind;
  source_id: string;
  unit?: string | null;
  value: number | string;
};

export type EvidenceSnapshotResponse = {
  content_available: boolean;
  content_deleted_at?: string | null;
  content_deletion_reason?: string | null;
  content_type: string;
  effective_at: string;
  observed_at?: string | null;
  payload_sha256: string;
  payload_size_bytes: number;
  provider_revision: string;
  published_at?: string | null;
  retrieved_at: string;
  rights_id: string;
  snapshot_id: string;
  source_id: string;
};

export type FootprintRequest = {
  coordinates: Array<Array<[number, number]>>;
  crs?: 'EPSG:4326';
};

export type HealthResponse = {
  service: string;
  status: string;
  version: string;
};

export type HTTPValidationError = {
  detail?: Array<ValidationError>;
};

export type InvestigationResponse = {
  actions?: Array<string>;
  capability_gaps?: Array<string>;
  collaboration_deadlock_count?: number;
  collaboration_fallback_reason?: string | null;
  collaboration_finding_count?: number;
  collaboration_iterations?: number | null;
  collaboration_status?: string | null;
  coordination_analytical_focus?: string | null;
  coordination_analytical_parameter_set_id?: string | null;
  coordination_analytical_release_id?: string | null;
  coordination_evidence_ids?: Array<string>;
  coordination_final_rationale?: string | null;
  coordination_missing_finding_keys?: Array<string>;
  coordination_required_finding_keys?: Array<string>;
  coordination_sufficient?: boolean | null;
  coordination_supervision_id?: string | null;
  coordination_supervisor_status?: string | null;
  coordination_termination_reason?: string | null;
  country?: string | null;
  decision_action?: string | null;
  decision_active_internal_states?: Array<string>;
  decision_autonomy_mode?: string | null;
  decision_requires_human_intervention?: boolean | null;
  decision_state_revision?: number | null;
  decision_termination_reason?: string | null;
  disaster?: string | null;
  evidence_count?: number;
  evidence_state_version?: string | null;
  geographic_scope?: string;
  information_needs?: Array<string>;
  output_modalities?: Array<string>;
  physical_event_id?: string | null;
  source_ids?: Array<string>;
  specialist_fallback_reason?: string | null;
  specialist_handoff_count?: number;
  specialist_latency_ms?: number;
  specialist_model_call_count?: number;
  specialist_provenance_validation_failures?: number;
  specialist_roles?: Array<string>;
  status: string;
  task_summary: string;
  termination_reason: string;
  triage_action?: string | null;
  triage_autonomy_mode?: string | null;
  triage_priority?: string | null;
  triage_requires_human_intervention?: boolean | null;
  triage_score?: number | null;
};

export type LineStringGeometryResponse = {
  coordinates: Array<[number, number]>;
  crs: 'EPSG:4326';
  type: 'LineString';
};

export type MapNavigationActionResponse = {
  bounds: [number, number, number, number];
  label: string;
  max_zoom?: number;
  type?: 'fit_bounds';
};

export type MapViewRequest = {
  center_latitude: number;
  center_longitude: number;
  zoom: number;
};

export type MeasurementKind =
  | 'magnitude'
  | 'intensity'
  | 'depth'
  | 'provider_significance'
  | 'confidence'
  | 'fire_radiative_power'
  | 'severity';

export type MultimodalAssetRequest = {
  attribution: string;
  canonical_url?: string | null;
  capture_role?: CaptureRole;
  captured_at?: string | null;
  content_base64: string;
  dataset_id?: string | null;
  declared_country_code?: string | null;
  declared_disaster?: Disaster | null;
  event_id_hint?: string | null;
  footprint?: FootprintRequest | null;
  license_name?: string | null;
  parent_asset_ids?: Array<string>;
  processing_level?: string | null;
};

export type MultimodalAssetResponse = {
  asset_id: string;
  byte_length: number;
  capture_role: string;
  captured_at?: string | null;
  content_sha256: string;
  declared_country_code?: string | null;
  declared_disaster?: string | null;
  eligibility: string;
  eligibility_reasons?: Array<string>;
  event_id_hint?: string | null;
  footprint?: PolygonGeometryResponse | null;
  height?: number | null;
  media_type: string;
  modality: string;
  parent_asset_ids?: Array<string>;
  processing_level?: string | null;
  retrieved_at: string;
  source: MultimodalSourceResponse;
  width?: number | null;
};

export type MultimodalSourceResponse = {
  attribution: string;
  canonical_url?: string | null;
  dataset_id?: string | null;
  license_name?: string | null;
  source_id: string;
};

export type MultimodalStateResponse = {
  assets?: Array<MultimodalAssetResponse>;
  associations?: Array<AssetEventAssociationResponse>;
  evaluated_at: string;
  evidence_world_state_version: string;
  observations?: Array<VisualObservationResponse>;
  physical_event_id: string;
  state_version: string;
};

export type OperatorActionRequest = {
  decision: OperatorDecision;
  evidence_ids?: Array<string>;
  policy_ids?: Array<string>;
  rationale: string;
  state_version: string;
};

export type OperatorActionResponse = {
  action_id: string;
  created: boolean;
  decision: OperatorDecision;
  operator_id: string;
  reviewed_at: string;
  state_version: string;
};

export type OperatorDecision = 'reviewed' | 'approved_bounded' | 'rejected';

export type PointGeometryResponse = {
  coordinates: [number, number];
  crs: 'EPSG:4326';
  type: 'Point';
};

export type PolygonGeometryResponse = {
  coordinates: Array<Array<[number, number]>>;
  crs: 'EPSG:4326';
  type: 'Polygon';
};

export type ProviderFreshnessResponse = {
  age_seconds?: number | null;
  consecutive_failures: number;
  effective_at?: string | null;
  expected_freshness_seconds: number;
  last_attempt_at?: string | null;
  last_success_at?: string | null;
  latest_error_code?: string | null;
  source_id: string;
  state: string;
};

export type ProviderTier = 'primary' | 'secondary';

export type ReadinessResponse = {
  model: string;
  model_available: boolean;
  ollama_available: boolean;
  status: string;
};

export type ReportSectionResponse = {
  content: string;
  title: string;
};

export type SatelliteImageryCatalogResponse = {
  products: Array<SatelliteImageryProductResponse>;
};

export type SatelliteImageryProductResponse = {
  access_mode: 'direct_gibs' | 'api';
  attribution: string;
  available: boolean;
  display_name: string;
  maximum_useful_zoom: number;
  provider_id: string;
  provider_name: string;
  source_id: string;
  temporal_mode: 'daily' | 'subdaily' | 'fixed';
  temporal_step_minutes?: number | null;
};

export type SelectedEventResponse = {
  disaster: string;
  event_id: string;
  event_time: string;
  geography_status: string;
  geometry?: EventGeometryResponse | null;
  location: string;
  measurements?: Array<EventMeasurementResponse>;
  provider_ids?: Array<string>;
  source: SourceResponse;
};

export type SourceAuthority =
  | 'national_authority'
  | 'scientific_authority'
  | 'humanitarian_aggregator'
  | 'secondary';

export type SourceMapFeatureResponse = {
  attribution: string;
  authority: 'official_source' | 'source_supplied';
  created_at: string;
  feature_id: string;
  feature_type: 'source';
  geometry:
    PointGeometryResponse | LineStringGeometryResponse | PolygonGeometryResponse;
  physical_event_id: string;
  semantic_kind: string;
  source_asset_ids: Array<string>;
  source_authority: 'official' | 'source_supplied';
  source_id: string;
  status: string;
  uncertainty: string;
  updated_at?: string | null;
};

export type SourceMapLayerResponse = {
  attribution: string;
  created_at: string;
  features: Array<SourceMapFeatureResponse>;
  layer_id: string;
  layer_type: 'source';
  physical_event_id: string;
  semantic_kind: string;
  source_asset_ids: Array<string>;
  source_ids: Array<string>;
  status: string;
  title: string;
  uncertainty: string;
  updated_at: string;
};

export type SourceResponse = {
  canonical_url: string;
  published_at?: string | null;
  publisher: string;
  retrieved_at: string;
  snapshot_id?: string | null;
  source_id: string;
  title: string;
  updated_at?: string | null;
};

export type ValidationError = {
  ctx?: Record<string, unknown>;
  input?: unknown;
  loc: Array<string | number>;
  msg: string;
  type: string;
};

export type VisualAnalysisConfigurationResponse = {
  adapter_version: string;
  analysis_version: string;
  maximum_output_tokens: number;
  model_digest?: string | null;
  model_id: string;
  preprocessing_version: string;
  prompt_version: string;
  seed: number;
  temperature: number;
};

export type VisualObservationResponse = {
  answer?: string | null;
  answerable?: boolean | null;
  asset_id: string;
  association_id: string;
  confidence?: number | null;
  configuration: VisualAnalysisConfigurationResponse;
  created_at: string;
  damage_level?: string | null;
  kind: string;
  modality: 'image';
  observation_id: string;
  physical_event_id: string;
  question?: string | null;
  safety_rule_ids?: Array<string>;
  status: string;
  truth_status: 'analytical';
  uncertainty: string;
  visual_cues?: Array<string>;
};
