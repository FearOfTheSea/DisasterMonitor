import type {
  AnalyticalMapFeatureResponse,
  AnalyticalMapLayerResponse,
  AssetEventAssociationResponse,
  AssistantRequest as ApiAssistantRequest,
  AssistantResponse as ApiAssistantResponse,
  CommonOperationalPictureResponse,
  ConversationMessageResponse,
  ConversationResponse,
  ConversationSummaryResponse,
  DecisionEstimateResponse,
  DecisionFactResponse,
  DecisionSupportResponse,
  CycloneMapLayerResponse,
  DisasterMediaGalleryResponse,
  DisasterMediaItemResponse,
  EventCoordinateResponse,
  EventGeometryResponse,
  EventMeasurementResponse,
  InvestigationResponse,
  LineStringGeometryResponse,
  MapNavigationActionResponse,
  MeasurementKind as ApiMeasurementKind,
  MultimodalAssetResponse,
  MultimodalSourceResponse,
  MultimodalStateResponse,
  PointGeometryResponse,
  PolygonGeometryResponse,
  ReportSectionResponse,
  SelectedEventResponse,
  SourceMapFeatureResponse,
  SourceMapLayerResponse,
  SourceResponse,
  VisualAnalysisConfigurationResponse,
  VisualObservationResponse,
} from '@/shared/api/generated/assistant';

export type MessageRole = 'user' | 'assistant';

export type MapView = {
  centerLatitude: number;
  centerLongitude: number;
  zoom: number;
};

export type AssistantRequest = ApiAssistantRequest;
export type MapNavigationAction = Omit<
  MapNavigationActionResponse,
  'type' | 'max_zoom'
> & {
  type: 'fit_bounds';
  max_zoom: number;
};
export type InvestigationSummary = Omit<
  InvestigationResponse,
  | 'information_needs'
  | 'output_modalities'
  | 'actions'
  | 'source_ids'
  | 'evidence_count'
  | 'capability_gaps'
> & {
  information_needs: string[];
  output_modalities: string[];
  actions: string[];
  source_ids: string[];
  evidence_count: number;
  capability_gaps: string[];
};
export type AssistantSource = SourceResponse;
export type MeasurementKind = ApiMeasurementKind;
export type EventMeasurement = EventMeasurementResponse;
export type EventCoordinate = EventCoordinateResponse;
export type EventGeometry = Omit<EventGeometryResponse, 'coordinates'> & {
  coordinates: EventCoordinate[];
};
export type CycloneMapLayer = Omit<CycloneMapLayerResponse, 'coordinates'> & {
  coordinates: CycloneMapLayerResponse['coordinates'];
};
export type SelectedEvent = Omit<
  SelectedEventResponse,
  'geometry' | 'measurements' | 'supplemental_geometry'
> & {
  geometry?: EventGeometry | null;
  measurements: EventMeasurement[];
  supplemental_geometry?: CycloneMapLayer[];
};
export type ReportSection = ReportSectionResponse;
export type DecisionFact = DecisionFactResponse;
export type DecisionFactStatementType = DecisionFact['statement_type'];
export type DecisionEstimate = DecisionEstimateResponse;
export type DecisionSupportArtifact = DecisionSupportResponse;
export type DisasterMediaItem = Omit<
  DisasterMediaItemResponse,
  'association_rule_ids'
> & {
  association_rule_ids: string[];
};
export type DisasterMediaGallery = Omit<
  DisasterMediaGalleryResponse,
  'items' | 'provider_ids' | 'warnings' | 'rejected_count'
> & {
  items: DisasterMediaItem[];
  provider_ids: string[];
  warnings: string[];
  rejected_count: number;
};
export type Wgs84PointGeometry = PointGeometryResponse;
export type Wgs84LineStringGeometry = LineStringGeometryResponse;
export type Wgs84PolygonGeometry = PolygonGeometryResponse;
export type CopGeometry =
  Wgs84PointGeometry | Wgs84LineStringGeometry | Wgs84PolygonGeometry;
export type MultimodalSource = MultimodalSourceResponse;
export type MultimodalAsset = Omit<
  MultimodalAssetResponse,
  'parent_asset_ids' | 'eligibility_reasons'
> & {
  parent_asset_ids: string[];
  eligibility_reasons: string[];
};
export type AssetEventAssociation = Omit<AssetEventAssociationResponse, 'rule_ids'> & {
  rule_ids: string[];
};
export type VisualAnalysisConfiguration = VisualAnalysisConfigurationResponse;
export type VisualObservation = Omit<
  VisualObservationResponse,
  'visual_cues' | 'safety_rule_ids'
> & {
  visual_cues: string[];
  safety_rule_ids: string[];
};
export type MultimodalEvidenceState = Omit<
  MultimodalStateResponse,
  'assets' | 'associations' | 'observations'
> & {
  assets: MultimodalAsset[];
  associations: AssetEventAssociation[];
  observations: VisualObservation[];
};
export type SourceMapFeature = SourceMapFeatureResponse;
export type AnalyticalMapFeature = AnalyticalMapFeatureResponse;
export type SourceMapLayer = SourceMapLayerResponse;
export type AnalyticalMapLayer = AnalyticalMapLayerResponse;
export type CopLayer = SourceMapLayer | AnalyticalMapLayer;
export type CommonOperationalPicture = CommonOperationalPictureResponse;

export type AssistantResponse = Omit<
  ApiAssistantResponse,
  'map_action' | 'selected_event' | 'investigation' | 'multimodal' | 'media_gallery'
> & {
  map_action?: MapNavigationAction | null;
  selected_event?: SelectedEvent | null;
  investigation?: InvestigationSummary | null;
  multimodal?: MultimodalEvidenceState | null;
  media_gallery?: DisasterMediaGallery | null;
};

export type OperatorAction = NonNullable<
  ApiAssistantResponse['operator_actions']
>[number];

export type ConversationSummary = ConversationSummaryResponse;
export type PersistedConversationMessage = Omit<
  ConversationMessageResponse,
  'assistant_response'
> & {
  assistant_response?: AssistantResponse | null;
};
export type PersistedConversation = Omit<ConversationResponse, 'messages'> & {
  messages: PersistedConversationMessage[];
};

export type ConversationMessage = {
  id: string;
  role: MessageRole;
  content: string;
  mapAction?: MapNavigationAction;
  operatorActions?: OperatorAction[];
  report?: AssistantReport;
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

export type ConversationStatus = 'idle' | 'loading' | 'error';
