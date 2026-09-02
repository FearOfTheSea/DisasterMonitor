import type {
  AssistantResponse as ApiAssistantResponse,
  ConversationResponse as ApiConversationResponse,
  DecisionSupportResponse,
  CycloneMapLayerResponse,
  DisasterMediaGalleryResponse,
  EventGeometryResponse,
  InvestigationResponse,
  InvestigationCaseResponse,
  InvestigationTargetResponse,
  MultimodalStateResponse,
} from '@/shared/api/generated/assistant';
import { matchesApiSchema } from '@/shared/api/generated/assistant';
import type {
  AssistantResponse,
  ConversationSummary,
  DisasterMediaGallery,
  InvestigationSummary,
  InvestigationCase,
  InvestigationTarget,
  MultimodalEvidenceState,
  PersistedConversation,
  PersistedConversationMessage,
} from '@/shared/types/assistant';
import { operatorActionsAreConsistent } from '@/features/assistant/model/operatorActions';
import { isMapNavigationAction } from '@/shared/validation/mapNavigation';
import {
  copMatchesMultimodalState,
  isCommonOperationalPicture,
  isMultimodalEvidenceState,
} from '@/shared/validation/multimodal';

export function validatedAssistantResponse(
  value: unknown,
): AssistantResponse | undefined {
  if (!matchesApiSchema('AssistantResponse', value)) return undefined;
  const response = normalizeAssistantResponse(value as ApiAssistantResponse);
  return assistantSemanticsAreValid(response) ? response : undefined;
}

export function validatedConversationSummaries(
  value: unknown,
): ConversationSummary[] | undefined {
  if (
    !Array.isArray(value) ||
    !value.every((item) => matchesApiSchema('ConversationSummaryResponse', item))
  ) {
    return undefined;
  }
  return value as ConversationSummary[];
}

export function validatedConversation(
  value: unknown,
): PersistedConversation | undefined {
  if (!matchesApiSchema('ConversationResponse', value)) return undefined;
  const conversation = value as ApiConversationResponse;
  const messages: PersistedConversationMessage[] = [];
  for (const message of conversation.messages ?? []) {
    const rawAssistantResponse = message.assistant_response;
    if (rawAssistantResponse !== undefined && rawAssistantResponse !== null) {
      const assistantResponse = validatedAssistantResponse(rawAssistantResponse);
      if (
        message.role !== 'assistant' ||
        assistantResponse === undefined ||
        assistantResponse.message !== message.content
      ) {
        return undefined;
      }
      messages.push({ ...message, assistant_response: assistantResponse });
    } else {
      messages.push({ ...message, assistant_response: rawAssistantResponse });
    }
  }
  return { ...conversation, messages };
}

function assistantSemanticsAreValid(response: AssistantResponse): boolean {
  if (response.map_action && !isMapNavigationAction(response.map_action)) return false;
  if (!operatorActionsAreConsistent(response.operator_actions ?? [])) return false;
  if (
    response.selected_event?.geometry &&
    !eventGeometryIsConsistent(response.selected_event.geometry)
  ) {
    return false;
  }
  if (
    response.investigation_case &&
    !investigationCaseIsConsistent(response.investigation_case)
  ) {
    return false;
  }
  if (
    response.selected_event &&
    !cycloneLayersAreConsistent(
      response.selected_event.disaster,
      response.selected_event.supplemental_geometry ?? [],
    )
  ) {
    return false;
  }
  if (
    response.decision_support &&
    !decisionSupportIsConsistent(response.decision_support)
  ) {
    return false;
  }
  if (response.multimodal && !isMultimodalEvidenceState(response.multimodal)) {
    return false;
  }
  if (
    response.common_operational_picture &&
    (!response.multimodal ||
      !isCommonOperationalPicture(response.common_operational_picture) ||
      !copMatchesMultimodalState(
        response.common_operational_picture,
        response.multimodal,
      ))
  ) {
    return false;
  }
  return (
    !response.media_gallery ||
    mediaGalleryIsConsistent(response.media_gallery, response.selected_event?.event_id)
  );
}

function cycloneLayersAreConsistent(
  disaster: string,
  layers: CycloneMapLayerResponse[],
): boolean {
  if (layers.length === 0) return true;
  if (disaster !== 'tropical_cyclone') return false;
  if (new Set(layers.map((layer) => layer.storm_id)).size !== 1) return false;
  return layers.every((layer) => {
    const minimumCoordinates = layer.geometry_kind === 'area' ? 3 : 2;
    const validTimes = [layer.issued_at, layer.valid_from, layer.valid_to].filter(
      (value): value is string => Boolean(value),
    );
    if (
      layer.coordinates.length < minimumCoordinates ||
      validTimes.some((value) => Number.isNaN(new Date(value).getTime())) ||
      (layer.valid_from &&
        layer.valid_to &&
        new Date(layer.valid_to).getTime() < new Date(layer.valid_from).getTime()) ||
      layer.coordinates.some(
        (point) =>
          point.latitude < -90 ||
          point.latitude > 90 ||
          point.longitude < -180 ||
          point.longitude > 180 ||
          (point.valid_at !== null &&
            point.valid_at !== undefined &&
            Number.isNaN(new Date(point.valid_at).getTime())),
      )
    ) {
      return false;
    }
    if (layer.semantic_role === 'provisional_track') {
      return (
        layer.geometry_kind === 'track' &&
        layer.provisional === true &&
        layer.coordinates.every((point) => Boolean(point.valid_at))
      );
    }
    if (layer.provisional) return false;
    if (layer.semantic_role === 'forecast_track') {
      return (
        layer.geometry_kind === 'track' &&
        layer.coordinates.every((point) => Boolean(point.valid_at))
      );
    }
    if (layer.semantic_role === 'uncertainty_area') {
      return (
        layer.geometry_kind === 'area' &&
        layer.wind_threshold == null &&
        layer.wind_threshold_unit == null
      );
    }
    return (
      layer.geometry_kind === 'area' &&
      typeof layer.wind_threshold === 'number' &&
      layer.wind_threshold > 0 &&
      Boolean(layer.wind_threshold_unit?.trim())
    );
  });
}

function eventGeometryIsConsistent(geometry: EventGeometryResponse): boolean {
  const requiredCoordinateCount = {
    point: 1,
    area: 3,
    track: 2,
    descriptive: 0,
  }[geometry.kind];
  const coordinates = geometry.coordinates ?? [];
  if (
    (geometry.kind === 'area' || geometry.kind === 'track'
      ? coordinates.length < requiredCoordinateCount
      : coordinates.length !== requiredCoordinateCount) ||
    coordinates.some(
      ({ latitude, longitude }) =>
        latitude < -90 || latitude > 90 || longitude < -180 || longitude > 180,
    )
  ) {
    return false;
  }
  return geometry.kind !== 'descriptive' || Boolean(geometry.description?.trim());
}

function decisionSupportIsConsistent(value: DecisionSupportResponse): boolean {
  const statementTypeByStatus: Record<string, string> = {
    source_backed_event: 'verified_fact',
    confirmed: 'verified_fact',
    preliminary: 'preliminary_observation',
    estimated: 'source_estimate',
    disputed: 'disputed_observation',
  };
  return (
    value.advisory_only === true &&
    value.facts.every(
      (fact) => fact.statement_type === statementTypeByStatus[fact.status],
    ) &&
    value.estimates.every((estimate) => estimate.statement_type === 'estimate')
  );
}

function mediaGalleryIsConsistent(
  gallery: DisasterMediaGallery,
  selectedEventId: string | undefined,
): boolean {
  if (
    gallery.items.length > 6 ||
    (selectedEventId !== undefined && gallery.event_id !== selectedEventId)
  ) {
    return false;
  }
  return gallery.items.every(
    (item) =>
      item.event_id === gallery.event_id &&
      item.physical_event_id === gallery.physical_event_id &&
      /^https?:\/\//.test(item.image_url) &&
      item.source_page_url.startsWith('https://') &&
      ['photographer', 'agency', 'publisher'].includes(item.credit_kind) &&
      ['licensed_reuse', 'source_preview'].includes(item.rights_status) &&
      [
        'aftermath',
        'rescue_effort',
        'relief_operation',
        'scientific_overview',
        'relevant_scene',
      ].includes(item.role) &&
      ['exact_event_link', 'corroborated'].includes(item.association_status) &&
      /^[a-f0-9]{64}$/.test(item.content_sha256) &&
      item.width > 0 &&
      item.height > 0,
  );
}

function normalizeAssistantResponse(value: ApiAssistantResponse): AssistantResponse {
  return {
    ...value,
    map_action: value.map_action
      ? {
          ...value.map_action,
          type: value.map_action.type ?? 'fit_bounds',
          max_zoom: value.map_action.max_zoom ?? 10,
        }
      : value.map_action,
    selected_event: value.selected_event
      ? {
          ...value.selected_event,
          geometry: value.selected_event.geometry
            ? {
                ...value.selected_event.geometry,
                coordinates: value.selected_event.geometry.coordinates ?? [],
              }
            : value.selected_event.geometry,
          measurements: value.selected_event.measurements ?? [],
          provider_ids: value.selected_event.provider_ids ?? [],
          supplemental_geometry: (value.selected_event.supplemental_geometry ?? []).map(
            (layer) => ({
              ...layer,
              coordinates: layer.coordinates ?? [],
            }),
          ),
        }
      : value.selected_event,
    investigation: value.investigation
      ? normalizeInvestigation(value.investigation)
      : value.investigation,
    investigation_case: value.investigation_case
      ? normalizeInvestigationCase(value.investigation_case)
      : value.investigation_case,
    multimodal: value.multimodal
      ? normalizeMultimodalState(value.multimodal)
      : value.multimodal,
    media_gallery: value.media_gallery
      ? normalizeMediaGallery(value.media_gallery)
      : value.media_gallery,
    operator_actions: value.operator_actions ?? [],
  };
}

function investigationCaseIsConsistent(value: InvestigationCase): boolean {
  if (
    value.targets.length !== 2 ||
    new Set(value.targets.map((target) => target.target_id)).size !== 2 ||
    new Set(value.targets.map((target) => target.disaster)).size !== 2
  ) {
    return false;
  }
  if (
    value.targets.some(
      (target) =>
        (target.selected_event !== null &&
          target.selected_event !== undefined &&
          (target.selected_event.disaster !== target.disaster ||
            (target.selected_event.geometry !== null &&
              target.selected_event.geometry !== undefined &&
              !eventGeometryIsConsistent(target.selected_event.geometry)))) ||
        !cycloneLayersAreConsistent(
          target.disaster,
          target.selected_event?.supplemental_geometry ?? [],
        ),
    )
  ) {
    return false;
  }
  const hasPartialBranch = value.targets.some((target) => target.partial);
  if (
    value.partial !== hasPartialBranch ||
    value.status !== (value.partial ? 'partial' : 'completed')
  ) {
    return false;
  }
  if (
    value.cross_hazard_assessment.status === 'associated' &&
    value.correlations.length === 0
  ) {
    return false;
  }
  if (
    value.cross_hazard_assessment.status !== 'associated' &&
    value.correlations.length > 0
  ) {
    return false;
  }
  const disasters = new Set(value.targets.map((target) => target.disaster));
  return value.correlations.every(
    (correlation) =>
      correlation.relationship === 'spatiotemporal_association' &&
      correlation.first_disaster !== correlation.second_disaster &&
      disasters.has(correlation.first_disaster) &&
      disasters.has(correlation.second_disaster) &&
      correlation.distance_km >= 0 &&
      correlation.time_delta_seconds >= 0,
  );
}

function normalizeInvestigationCase(
  value: InvestigationCaseResponse,
): InvestigationCase {
  return {
    ...value,
    targets: (value.targets ?? []).map((target) =>
      normalizeInvestigationTarget(target),
    ),
    correlations: (value.correlations ?? []).map((correlation) => ({
      ...correlation,
      source_ids: correlation.source_ids ?? [],
    })),
  };
}

function normalizeInvestigationTarget(
  value: InvestigationTargetResponse,
): InvestigationTarget {
  return {
    ...value,
    selected_event: value.selected_event
      ? {
          ...value.selected_event,
          geometry: value.selected_event.geometry
            ? {
                ...value.selected_event.geometry,
                coordinates: value.selected_event.geometry.coordinates ?? [],
              }
            : value.selected_event.geometry,
          measurements: value.selected_event.measurements ?? [],
          provider_ids: value.selected_event.provider_ids ?? [],
          supplemental_geometry: (value.selected_event.supplemental_geometry ?? []).map(
            (layer) => ({ ...layer, coordinates: layer.coordinates ?? [] }),
          ),
        }
      : value.selected_event,
    sources: value.sources ?? [],
    warnings: value.warnings ?? [],
    sections: value.sections ?? [],
  };
}

function normalizeInvestigation(value: InvestigationResponse): InvestigationSummary {
  return {
    ...value,
    information_needs: value.information_needs ?? [],
    output_modalities: value.output_modalities ?? [],
    actions: value.actions ?? [],
    source_ids: value.source_ids ?? [],
    evidence_count: value.evidence_count ?? 0,
    capability_gaps: value.capability_gaps ?? [],
  };
}

function normalizeMultimodalState(
  value: MultimodalStateResponse,
): MultimodalEvidenceState {
  return {
    ...value,
    assets: (value.assets ?? []).map((asset) => ({
      ...asset,
      parent_asset_ids: asset.parent_asset_ids ?? [],
      eligibility_reasons: asset.eligibility_reasons ?? [],
    })),
    associations: (value.associations ?? []).map((association) => ({
      ...association,
      rule_ids: association.rule_ids ?? [],
    })),
    observations: (value.observations ?? []).map((observation) => ({
      ...observation,
      visual_cues: observation.visual_cues ?? [],
      safety_rule_ids: observation.safety_rule_ids ?? [],
    })),
  };
}

function normalizeMediaGallery(
  value: DisasterMediaGalleryResponse,
): DisasterMediaGallery {
  return {
    ...value,
    items: (value.items ?? []).map((item) => ({
      ...item,
      association_rule_ids: item.association_rule_ids ?? [],
    })),
    rejected_count: value.rejected_count ?? 0,
    provider_ids: value.provider_ids ?? [],
    warnings: value.warnings ?? [],
  };
}
