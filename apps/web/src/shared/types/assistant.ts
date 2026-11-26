import type {
  AnalyticalMapFeatureResponse,
  AnalyticalMapLayerResponse,
  AssetEventAssociationResponse,
  AssistantRequest as ApiAssistantRequest,
  AssistantResponse as ApiAssistantResponse,
  CommonOperationalPictureResponse,
  CompoundHazardCorrelationResponse,
  ConversationMessageResponse,
  ConversationResponse,
  ConversationSummaryResponse,
  DecisionFactResponse,
  DecisionSupportResponse,
  CycloneMapLayerResponse,
  DisasterMediaGalleryResponse,
  DisasterMediaItemResponse,
  EvidenceClaimResponse,
  EvidenceClaimVariantResponse,
  EvidenceTimelineEntryResponse,
  EventCoordinateResponse,
  EventGeometryResponse,
  EventMeasurementResponse,
  InvestigationResponse,
  InvestigationCaseResponse,
  InvestigationTargetResponse,
  LineStringGeometryResponse,
  MapNavigationActionResponse,
  MultimodalAssetResponse,
  MultimodalStateResponse,
  PointGeometryResponse,
  PolygonGeometryResponse,
  ReportSectionResponse,
  SelectedEventResponse,
  SourceMapFeatureResponse,
  SourceMapLayerResponse,
  SourceResponse,
  VisualObservationResponse,
} from '@/shared/api/generated/assistant';

type MessageRole = 'user' | 'assistant';

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
type CompoundHazardCorrelation = Omit<
  CompoundHazardCorrelationResponse,
  'source_ids'
> & {
  source_ids: string[];
};
export type InvestigationTarget = Omit<
  InvestigationTargetResponse,
  'selected_event' | 'sources' | 'warnings' | 'sections'
> & {
  selected_event?: SelectedEvent | null;
  sources: AssistantSource[];
  warnings: string[];
  sections: ReportSection[];
};
export type InvestigationCase = Omit<
  InvestigationCaseResponse,
  'targets' | 'correlations'
> & {
  targets: InvestigationTarget[];
  correlations: CompoundHazardCorrelation[];
};
type AssistantSource = SourceResponse;
export type EvidenceClaim = EvidenceClaimResponse;
export type EvidenceClaimVariant = EvidenceClaimVariantResponse;
export type EvidenceTimelineEntry = EvidenceTimelineEntryResponse;
type EventMeasurement = EventMeasurementResponse;
type EventCoordinate = EventCoordinateResponse;
type EventGeometry = Omit<EventGeometryResponse, 'coordinates'> & {
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
type ReportSection = ReportSectionResponse;
type DecisionFact = DecisionFactResponse;
export type DecisionFactStatementType = DecisionFact['statement_type'];
export type DecisionSupportArtifact = DecisionSupportResponse;
type DisasterMediaItem = Omit<DisasterMediaItemResponse, 'association_rule_ids'> & {
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
type Wgs84PointGeometry = PointGeometryResponse;
type Wgs84LineStringGeometry = LineStringGeometryResponse;
type Wgs84PolygonGeometry = PolygonGeometryResponse;
export type CopGeometry =
  Wgs84PointGeometry | Wgs84LineStringGeometry | Wgs84PolygonGeometry;
type MultimodalAsset = Omit<
  MultimodalAssetResponse,
  'parent_asset_ids' | 'eligibility_reasons'
> & {
  parent_asset_ids: string[];
  eligibility_reasons: string[];
};
type AssetEventAssociation = Omit<AssetEventAssociationResponse, 'rule_ids'> & {
  rule_ids: string[];
};
type VisualObservation = Omit<
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
type SourceMapLayer = SourceMapLayerResponse;
type AnalyticalMapLayer = AnalyticalMapLayerResponse;
export type CopLayer = SourceMapLayer | AnalyticalMapLayer;
export type CommonOperationalPicture = CommonOperationalPictureResponse;

export type AssistantResponse = Omit<
  ApiAssistantResponse,
  | 'map_action'
  | 'selected_event'
  | 'investigation'
  | 'investigation_case'
  | 'multimodal'
  | 'media_gallery'
> & {
  map_action?: MapNavigationAction | null;
  selected_event?: SelectedEvent | null;
  investigation?: InvestigationSummary | null;
  investigation_case?: InvestigationCase | null;
  multimodal?: MultimodalEvidenceState | null;
  media_gallery?: DisasterMediaGallery | null;
  claims: EvidenceClaim[];
  timeline: EvidenceTimelineEntry[];
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
  originalMessage?: string;
  responseLanguage?: string;
  selectedEvent?: SelectedEvent;
  retrievalTime?: string;
  sources: AssistantSource[];
  warnings: string[];
  sections: ReportSection[];
  partial: boolean;
  investigation?: InvestigationSummary;
  investigationCase?: InvestigationCase;
  decisionSupport?: DecisionSupportArtifact;
  multimodal?: MultimodalEvidenceState;
  commonOperationalPicture?: CommonOperationalPicture;
  mediaGallery?: DisasterMediaGallery;
  claims: EvidenceClaim[];
  timeline: EvidenceTimelineEntry[];
};

export type ConversationStatus = 'idle' | 'loading' | 'error';
