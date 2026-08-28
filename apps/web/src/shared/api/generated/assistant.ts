// Generated from the DisasterMonitor backend OpenAPI schema.
// Run `npm run generate:api-contract` after backend schema changes.

import { matchesOpenApiSchema } from '@/shared/api/openapiSchema';

const apiSchemas = {
  AnalyticalMapFeatureResponse: {
    properties: {
      attribution: {
        type: 'string',
      },
      authority: {
        const: 'analytical_generated',
        type: 'string',
      },
      confidence: {
        anyOf: [
          {
            type: 'number',
          },
          {
            type: 'null',
          },
        ],
      },
      created_at: {
        format: 'date-time',
        type: 'string',
      },
      feature_id: {
        type: 'string',
      },
      feature_type: {
        const: 'analytical',
        type: 'string',
      },
      geometry: {
        anyOf: [
          {
            $ref: '#/components/schemas/PointGeometryResponse',
          },
          {
            $ref: '#/components/schemas/LineStringGeometryResponse',
          },
          {
            $ref: '#/components/schemas/PolygonGeometryResponse',
          },
        ],
      },
      physical_event_id: {
        type: 'string',
      },
      semantic_kind: {
        type: 'string',
      },
      source_asset_ids: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
      status: {
        type: 'string',
      },
      uncertainty: {
        type: 'string',
      },
      updated_at: {
        anyOf: [
          {
            format: 'date-time',
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      visual_observation_ids: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
    },
    required: [
      'feature_type',
      'feature_id',
      'physical_event_id',
      'source_asset_ids',
      'visual_observation_ids',
      'created_at',
      'semantic_kind',
      'geometry',
      'attribution',
      'status',
      'uncertainty',
      'authority',
    ],
    type: 'object',
  },
  AnalyticalMapLayerResponse: {
    properties: {
      attribution: {
        type: 'string',
      },
      created_at: {
        format: 'date-time',
        type: 'string',
      },
      features: {
        items: {
          $ref: '#/components/schemas/AnalyticalMapFeatureResponse',
        },
        type: 'array',
      },
      layer_id: {
        type: 'string',
      },
      layer_type: {
        const: 'analytical',
        type: 'string',
      },
      physical_event_id: {
        type: 'string',
      },
      semantic_kind: {
        type: 'string',
      },
      source_asset_ids: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
      status: {
        type: 'string',
      },
      title: {
        type: 'string',
      },
      uncertainty: {
        type: 'string',
      },
      updated_at: {
        format: 'date-time',
        type: 'string',
      },
      visual_observation_ids: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
    },
    required: [
      'layer_type',
      'layer_id',
      'physical_event_id',
      'title',
      'semantic_kind',
      'features',
      'source_asset_ids',
      'visual_observation_ids',
      'created_at',
      'updated_at',
      'status',
      'uncertainty',
      'attribution',
    ],
    type: 'object',
  },
  AssetEventAssociationResponse: {
    properties: {
      asset_id: {
        type: 'string',
      },
      association_id: {
        type: 'string',
      },
      country_match: {
        anyOf: [
          {
            type: 'boolean',
          },
          {
            type: 'null',
          },
        ],
      },
      detail: {
        type: 'string',
      },
      disaster_match: {
        anyOf: [
          {
            type: 'boolean',
          },
          {
            type: 'null',
          },
        ],
      },
      distance_km: {
        anyOf: [
          {
            type: 'number',
          },
          {
            type: 'null',
          },
        ],
      },
      event_id_match: {
        anyOf: [
          {
            type: 'boolean',
          },
          {
            type: 'null',
          },
        ],
      },
      geography_match: {
        anyOf: [
          {
            type: 'boolean',
          },
          {
            type: 'null',
          },
        ],
      },
      physical_event_id: {
        type: 'string',
      },
      rule_ids: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
      status: {
        type: 'string',
      },
      time_delta_seconds: {
        anyOf: [
          {
            type: 'number',
          },
          {
            type: 'null',
          },
        ],
      },
      time_match: {
        anyOf: [
          {
            type: 'boolean',
          },
          {
            type: 'null',
          },
        ],
      },
    },
    required: ['association_id', 'asset_id', 'physical_event_id', 'status', 'detail'],
    type: 'object',
  },
  AssistantResponse: {
    properties: {
      common_operational_picture: {
        anyOf: [
          {
            $ref: '#/components/schemas/CommonOperationalPictureResponse',
          },
          {
            type: 'null',
          },
        ],
      },
      conversation_id: {
        type: 'string',
      },
      decision_support: {
        anyOf: [
          {
            $ref: '#/components/schemas/DecisionSupportResponse',
          },
          {
            type: 'null',
          },
        ],
      },
      investigation: {
        anyOf: [
          {
            $ref: '#/components/schemas/InvestigationResponse',
          },
          {
            type: 'null',
          },
        ],
      },
      map_action: {
        anyOf: [
          {
            $ref: '#/components/schemas/MapNavigationActionResponse',
          },
          {
            type: 'null',
          },
        ],
      },
      media_gallery: {
        anyOf: [
          {
            $ref: '#/components/schemas/DisasterMediaGalleryResponse',
          },
          {
            type: 'null',
          },
        ],
      },
      message: {
        type: 'string',
      },
      model: {
        type: 'string',
      },
      multimodal: {
        anyOf: [
          {
            $ref: '#/components/schemas/MultimodalStateResponse',
          },
          {
            type: 'null',
          },
        ],
      },
      partial: {
        type: 'boolean',
      },
      response_type: {
        type: 'string',
      },
      retrieval_time: {
        anyOf: [
          {
            format: 'date-time',
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      sections: {
        items: {
          $ref: '#/components/schemas/ReportSectionResponse',
        },
        type: 'array',
      },
      selected_event: {
        anyOf: [
          {
            $ref: '#/components/schemas/SelectedEventResponse',
          },
          {
            type: 'null',
          },
        ],
      },
      sources: {
        items: {
          $ref: '#/components/schemas/SourceResponse',
        },
        type: 'array',
      },
      warnings: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
    },
    required: ['message', 'conversation_id', 'model'],
    type: 'object',
  },
  CommonOperationalPictureResponse: {
    properties: {
      cop_id: {
        type: 'string',
      },
      created_at: {
        format: 'date-time',
        type: 'string',
      },
      layers: {
        items: {
          anyOf: [
            {
              $ref: '#/components/schemas/SourceMapLayerResponse',
            },
            {
              $ref: '#/components/schemas/AnalyticalMapLayerResponse',
            },
          ],
        },
        type: 'array',
      },
      multimodal_state_version: {
        type: 'string',
      },
      physical_event_id: {
        type: 'string',
      },
      status: {
        type: 'string',
      },
      updated_at: {
        format: 'date-time',
        type: 'string',
      },
    },
    required: [
      'cop_id',
      'physical_event_id',
      'multimodal_state_version',
      'created_at',
      'updated_at',
      'status',
      'layers',
    ],
    type: 'object',
  },
  ConversationMessageResponse: {
    properties: {
      assistant_response: {
        anyOf: [
          {
            $ref: '#/components/schemas/AssistantResponse',
          },
          {
            type: 'null',
          },
        ],
      },
      content: {
        type: 'string',
      },
      created_at: {
        format: 'date-time',
        type: 'string',
      },
      id: {
        type: 'string',
      },
      role: {
        enum: ['user', 'assistant'],
        type: 'string',
      },
    },
    required: ['id', 'role', 'content', 'created_at'],
    type: 'object',
  },
  ConversationResponse: {
    properties: {
      conversation_id: {
        type: 'string',
      },
      created_at: {
        format: 'date-time',
        type: 'string',
      },
      messages: {
        items: {
          $ref: '#/components/schemas/ConversationMessageResponse',
        },
        type: 'array',
      },
      updated_at: {
        format: 'date-time',
        type: 'string',
      },
    },
    required: ['conversation_id', 'created_at', 'updated_at'],
    type: 'object',
  },
  ConversationSummaryResponse: {
    properties: {
      conversation_id: {
        type: 'string',
      },
      created_at: {
        format: 'date-time',
        type: 'string',
      },
      preview: {
        type: 'string',
      },
      updated_at: {
        format: 'date-time',
        type: 'string',
      },
    },
    required: ['conversation_id', 'created_at', 'updated_at', 'preview'],
    type: 'object',
  },
  DecisionEstimateResponse: {
    properties: {
      contradicting_evidence_ids: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
      estimate_id: {
        type: 'string',
      },
      probability: {
        type: 'number',
      },
      proposition: {
        type: 'string',
      },
      rationale_rule_ids: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
      statement_type: {
        type: 'string',
      },
      supporting_evidence_ids: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
      uncertain_evidence_ids: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
    },
    required: [
      'estimate_id',
      'proposition',
      'probability',
      'supporting_evidence_ids',
      'contradicting_evidence_ids',
      'uncertain_evidence_ids',
      'rationale_rule_ids',
      'statement_type',
    ],
    type: 'object',
  },
  DecisionFactResponse: {
    properties: {
      evidence_ids: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
      fact_id: {
        type: 'string',
      },
      source_ids: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
      statement: {
        type: 'string',
      },
      statement_type: {
        type: 'string',
      },
      status: {
        type: 'string',
      },
    },
    required: [
      'fact_id',
      'statement',
      'evidence_ids',
      'source_ids',
      'status',
      'statement_type',
    ],
    type: 'object',
  },
  DecisionSupportResponse: {
    properties: {
      advisory_only: {
        type: 'boolean',
      },
      artifact_id: {
        type: 'string',
      },
      estimates: {
        items: {
          $ref: '#/components/schemas/DecisionEstimateResponse',
        },
        type: 'array',
      },
      evidence_state_version: {
        type: 'string',
      },
      facts: {
        items: {
          $ref: '#/components/schemas/DecisionFactResponse',
        },
        type: 'array',
      },
      recommendation_status: {
        type: 'string',
      },
      scenario_mode: {
        type: 'string',
      },
    },
    required: [
      'artifact_id',
      'evidence_state_version',
      'facts',
      'estimates',
      'scenario_mode',
      'recommendation_status',
      'advisory_only',
    ],
    type: 'object',
  },
  DisasterMediaGalleryResponse: {
    properties: {
      event_id: {
        type: 'string',
      },
      generated_at: {
        format: 'date-time',
        type: 'string',
      },
      items: {
        items: {
          $ref: '#/components/schemas/DisasterMediaItemResponse',
        },
        type: 'array',
      },
      physical_event_id: {
        type: 'string',
      },
      provider_ids: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
      rejected_count: {
        type: 'integer',
      },
      warnings: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
    },
    required: ['event_id', 'physical_event_id', 'generated_at'],
    type: 'object',
  },
  DisasterMediaItemResponse: {
    properties: {
      association_detail: {
        type: 'string',
      },
      association_rule_ids: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
      association_status: {
        type: 'string',
      },
      caption: {
        type: 'string',
      },
      captured_at: {
        anyOf: [
          {
            format: 'date-time',
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      content_sha256: {
        type: 'string',
      },
      credit: {
        type: 'string',
      },
      credit_kind: {
        type: 'string',
      },
      event_id: {
        type: 'string',
      },
      height: {
        type: 'integer',
      },
      image_url: {
        type: 'string',
      },
      license_name: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      license_url: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      media_id: {
        type: 'string',
      },
      physical_event_id: {
        type: 'string',
      },
      published_at: {
        format: 'date-time',
        type: 'string',
      },
      publisher: {
        type: 'string',
      },
      rights_status: {
        type: 'string',
      },
      role: {
        type: 'string',
      },
      source_id: {
        type: 'string',
      },
      source_page_url: {
        type: 'string',
      },
      uncertainty: {
        type: 'string',
      },
      width: {
        type: 'integer',
      },
    },
    required: [
      'media_id',
      'image_url',
      'event_id',
      'physical_event_id',
      'source_id',
      'publisher',
      'source_page_url',
      'caption',
      'credit',
      'credit_kind',
      'published_at',
      'rights_status',
      'role',
      'association_status',
      'association_detail',
      'uncertainty',
      'content_sha256',
      'width',
      'height',
    ],
    type: 'object',
  },
  EventCoordinateResponse: {
    properties: {
      latitude: {
        maximum: 90,
        minimum: -90,
        type: 'number',
      },
      longitude: {
        maximum: 180,
        minimum: -180,
        type: 'number',
      },
    },
    required: ['latitude', 'longitude'],
    type: 'object',
  },
  EventGeometryResponse: {
    properties: {
      coordinates: {
        items: {
          $ref: '#/components/schemas/EventCoordinateResponse',
        },
        type: 'array',
      },
      description: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      estimated: {
        type: 'boolean',
      },
      kind: {
        enum: ['point', 'area', 'track', 'descriptive'],
        type: 'string',
      },
      source_id: {
        type: 'string',
      },
    },
    required: ['kind', 'source_id'],
    type: 'object',
  },
  EventMeasurementResponse: {
    properties: {
      kind: {
        $ref: '#/components/schemas/MeasurementKind',
      },
      source_id: {
        type: 'string',
      },
      unit: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      value: {
        anyOf: [
          {
            type: 'number',
          },
          {
            type: 'string',
          },
        ],
      },
    },
    required: ['kind', 'value', 'source_id'],
    type: 'object',
  },
  InvestigationResponse: {
    properties: {
      actions: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
      capability_gaps: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
      collaboration_deadlock_count: {
        type: 'integer',
      },
      collaboration_fallback_reason: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      collaboration_finding_count: {
        type: 'integer',
      },
      collaboration_iterations: {
        anyOf: [
          {
            type: 'integer',
          },
          {
            type: 'null',
          },
        ],
      },
      collaboration_status: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      coordination_analytical_focus: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      coordination_analytical_parameter_set_id: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      coordination_analytical_release_id: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      coordination_evidence_ids: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
      coordination_final_rationale: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      coordination_missing_finding_keys: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
      coordination_required_finding_keys: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
      coordination_sufficient: {
        anyOf: [
          {
            type: 'boolean',
          },
          {
            type: 'null',
          },
        ],
      },
      coordination_supervision_id: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      coordination_supervisor_status: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      coordination_termination_reason: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      country: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      decision_action: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      decision_active_internal_states: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
      decision_autonomy_mode: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      decision_requires_human_intervention: {
        anyOf: [
          {
            type: 'boolean',
          },
          {
            type: 'null',
          },
        ],
      },
      decision_state_revision: {
        anyOf: [
          {
            type: 'integer',
          },
          {
            type: 'null',
          },
        ],
      },
      decision_termination_reason: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      disaster: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      evidence_count: {
        type: 'integer',
      },
      evidence_state_version: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      geographic_scope: {
        type: 'string',
      },
      information_needs: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
      output_modalities: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
      physical_event_id: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      source_ids: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
      specialist_fallback_reason: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      specialist_handoff_count: {
        type: 'integer',
      },
      specialist_latency_ms: {
        type: 'number',
      },
      specialist_model_call_count: {
        type: 'integer',
      },
      specialist_provenance_validation_failures: {
        type: 'integer',
      },
      specialist_roles: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
      status: {
        type: 'string',
      },
      task_summary: {
        type: 'string',
      },
      termination_reason: {
        type: 'string',
      },
      triage_action: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      triage_autonomy_mode: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      triage_priority: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      triage_requires_human_intervention: {
        anyOf: [
          {
            type: 'boolean',
          },
          {
            type: 'null',
          },
        ],
      },
      triage_score: {
        anyOf: [
          {
            type: 'integer',
          },
          {
            type: 'null',
          },
        ],
      },
    },
    required: ['status', 'task_summary', 'termination_reason'],
    type: 'object',
  },
  LineStringGeometryResponse: {
    properties: {
      coordinates: {
        items: {
          maxItems: 2,
          minItems: 2,
          prefixItems: [
            {
              type: 'number',
            },
            {
              type: 'number',
            },
          ],
          type: 'array',
        },
        type: 'array',
      },
      crs: {
        const: 'EPSG:4326',
        type: 'string',
      },
      type: {
        const: 'LineString',
        type: 'string',
      },
    },
    required: ['type', 'coordinates', 'crs'],
    type: 'object',
  },
  MapNavigationActionResponse: {
    additionalProperties: false,
    properties: {
      bounds: {
        maxItems: 4,
        minItems: 4,
        prefixItems: [
          {
            type: 'number',
          },
          {
            type: 'number',
          },
          {
            type: 'number',
          },
          {
            type: 'number',
          },
        ],
        type: 'array',
      },
      label: {
        maxLength: 160,
        minLength: 1,
        type: 'string',
      },
      max_zoom: {
        maximum: 18,
        minimum: 2,
        type: 'number',
      },
      type: {
        const: 'fit_bounds',
        type: 'string',
      },
    },
    required: ['bounds', 'label'],
    type: 'object',
  },
  MeasurementKind: {
    enum: [
      'magnitude',
      'intensity',
      'depth',
      'provider_significance',
      'confidence',
      'fire_radiative_power',
      'severity',
    ],
    type: 'string',
  },
  MultimodalAssetResponse: {
    properties: {
      asset_id: {
        type: 'string',
      },
      byte_length: {
        type: 'integer',
      },
      capture_role: {
        type: 'string',
      },
      captured_at: {
        anyOf: [
          {
            format: 'date-time',
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      content_sha256: {
        type: 'string',
      },
      declared_country_code: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      declared_disaster: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      eligibility: {
        type: 'string',
      },
      eligibility_reasons: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
      event_id_hint: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      footprint: {
        anyOf: [
          {
            $ref: '#/components/schemas/PolygonGeometryResponse',
          },
          {
            type: 'null',
          },
        ],
      },
      height: {
        anyOf: [
          {
            type: 'integer',
          },
          {
            type: 'null',
          },
        ],
      },
      media_type: {
        type: 'string',
      },
      modality: {
        type: 'string',
      },
      parent_asset_ids: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
      processing_level: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      retrieved_at: {
        format: 'date-time',
        type: 'string',
      },
      source: {
        $ref: '#/components/schemas/MultimodalSourceResponse',
      },
      width: {
        anyOf: [
          {
            type: 'integer',
          },
          {
            type: 'null',
          },
        ],
      },
    },
    required: [
      'asset_id',
      'source',
      'retrieved_at',
      'modality',
      'media_type',
      'content_sha256',
      'byte_length',
      'capture_role',
      'eligibility',
    ],
    type: 'object',
  },
  MultimodalSourceResponse: {
    properties: {
      attribution: {
        type: 'string',
      },
      canonical_url: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      dataset_id: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      license_name: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      source_id: {
        type: 'string',
      },
    },
    required: ['source_id', 'attribution'],
    type: 'object',
  },
  MultimodalStateResponse: {
    properties: {
      assets: {
        items: {
          $ref: '#/components/schemas/MultimodalAssetResponse',
        },
        type: 'array',
      },
      associations: {
        items: {
          $ref: '#/components/schemas/AssetEventAssociationResponse',
        },
        type: 'array',
      },
      evaluated_at: {
        format: 'date-time',
        type: 'string',
      },
      evidence_world_state_version: {
        type: 'string',
      },
      observations: {
        items: {
          $ref: '#/components/schemas/VisualObservationResponse',
        },
        type: 'array',
      },
      physical_event_id: {
        type: 'string',
      },
      state_version: {
        type: 'string',
      },
    },
    required: [
      'state_version',
      'evidence_world_state_version',
      'physical_event_id',
      'evaluated_at',
    ],
    type: 'object',
  },
  PointGeometryResponse: {
    properties: {
      coordinates: {
        maxItems: 2,
        minItems: 2,
        prefixItems: [
          {
            type: 'number',
          },
          {
            type: 'number',
          },
        ],
        type: 'array',
      },
      crs: {
        const: 'EPSG:4326',
        type: 'string',
      },
      type: {
        const: 'Point',
        type: 'string',
      },
    },
    required: ['type', 'coordinates', 'crs'],
    type: 'object',
  },
  PolygonGeometryResponse: {
    properties: {
      coordinates: {
        items: {
          items: {
            maxItems: 2,
            minItems: 2,
            prefixItems: [
              {
                type: 'number',
              },
              {
                type: 'number',
              },
            ],
            type: 'array',
          },
          type: 'array',
        },
        type: 'array',
      },
      crs: {
        const: 'EPSG:4326',
        type: 'string',
      },
      type: {
        const: 'Polygon',
        type: 'string',
      },
    },
    required: ['type', 'coordinates', 'crs'],
    type: 'object',
  },
  ReportSectionResponse: {
    properties: {
      content: {
        type: 'string',
      },
      title: {
        type: 'string',
      },
    },
    required: ['title', 'content'],
    type: 'object',
  },
  SelectedEventResponse: {
    properties: {
      disaster: {
        type: 'string',
      },
      event_id: {
        type: 'string',
      },
      event_time: {
        format: 'date-time',
        type: 'string',
      },
      geography_status: {
        type: 'string',
      },
      geometry: {
        anyOf: [
          {
            $ref: '#/components/schemas/EventGeometryResponse',
          },
          {
            type: 'null',
          },
        ],
      },
      location: {
        type: 'string',
      },
      measurements: {
        items: {
          $ref: '#/components/schemas/EventMeasurementResponse',
        },
        type: 'array',
      },
      provider_ids: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
      source: {
        $ref: '#/components/schemas/SourceResponse',
      },
    },
    required: [
      'event_id',
      'disaster',
      'location',
      'event_time',
      'source',
      'geography_status',
    ],
    type: 'object',
  },
  SourceMapFeatureResponse: {
    properties: {
      attribution: {
        type: 'string',
      },
      authority: {
        enum: ['official_source', 'source_supplied'],
        type: 'string',
      },
      created_at: {
        format: 'date-time',
        type: 'string',
      },
      feature_id: {
        type: 'string',
      },
      feature_type: {
        const: 'source',
        type: 'string',
      },
      geometry: {
        anyOf: [
          {
            $ref: '#/components/schemas/PointGeometryResponse',
          },
          {
            $ref: '#/components/schemas/LineStringGeometryResponse',
          },
          {
            $ref: '#/components/schemas/PolygonGeometryResponse',
          },
        ],
      },
      physical_event_id: {
        type: 'string',
      },
      semantic_kind: {
        type: 'string',
      },
      source_asset_ids: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
      source_authority: {
        enum: ['official', 'source_supplied'],
        type: 'string',
      },
      source_id: {
        type: 'string',
      },
      status: {
        type: 'string',
      },
      uncertainty: {
        type: 'string',
      },
      updated_at: {
        anyOf: [
          {
            format: 'date-time',
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
    },
    required: [
      'feature_type',
      'feature_id',
      'physical_event_id',
      'source_id',
      'source_asset_ids',
      'created_at',
      'semantic_kind',
      'geometry',
      'attribution',
      'status',
      'uncertainty',
      'authority',
      'source_authority',
    ],
    type: 'object',
  },
  SourceMapLayerResponse: {
    properties: {
      attribution: {
        type: 'string',
      },
      created_at: {
        format: 'date-time',
        type: 'string',
      },
      features: {
        items: {
          $ref: '#/components/schemas/SourceMapFeatureResponse',
        },
        type: 'array',
      },
      layer_id: {
        type: 'string',
      },
      layer_type: {
        const: 'source',
        type: 'string',
      },
      physical_event_id: {
        type: 'string',
      },
      semantic_kind: {
        type: 'string',
      },
      source_asset_ids: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
      source_ids: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
      status: {
        type: 'string',
      },
      title: {
        type: 'string',
      },
      uncertainty: {
        type: 'string',
      },
      updated_at: {
        format: 'date-time',
        type: 'string',
      },
    },
    required: [
      'layer_type',
      'layer_id',
      'physical_event_id',
      'title',
      'semantic_kind',
      'features',
      'source_ids',
      'source_asset_ids',
      'created_at',
      'updated_at',
      'status',
      'uncertainty',
      'attribution',
    ],
    type: 'object',
  },
  SourceResponse: {
    properties: {
      canonical_url: {
        type: 'string',
      },
      published_at: {
        anyOf: [
          {
            format: 'date-time',
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      publisher: {
        type: 'string',
      },
      retrieved_at: {
        format: 'date-time',
        type: 'string',
      },
      snapshot_id: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      source_id: {
        type: 'string',
      },
      title: {
        type: 'string',
      },
      updated_at: {
        anyOf: [
          {
            format: 'date-time',
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
    },
    required: ['source_id', 'publisher', 'title', 'canonical_url', 'retrieved_at'],
    type: 'object',
  },
  VisualAnalysisConfigurationResponse: {
    properties: {
      adapter_version: {
        type: 'string',
      },
      analysis_version: {
        type: 'string',
      },
      maximum_output_tokens: {
        type: 'integer',
      },
      model_digest: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      model_id: {
        type: 'string',
      },
      preprocessing_version: {
        type: 'string',
      },
      prompt_version: {
        type: 'string',
      },
      seed: {
        type: 'integer',
      },
      temperature: {
        type: 'number',
      },
    },
    required: [
      'model_id',
      'adapter_version',
      'analysis_version',
      'prompt_version',
      'preprocessing_version',
      'maximum_output_tokens',
      'temperature',
      'seed',
    ],
    type: 'object',
  },
  VisualObservationResponse: {
    properties: {
      answer: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      answerable: {
        anyOf: [
          {
            type: 'boolean',
          },
          {
            type: 'null',
          },
        ],
      },
      asset_id: {
        type: 'string',
      },
      association_id: {
        type: 'string',
      },
      confidence: {
        anyOf: [
          {
            type: 'number',
          },
          {
            type: 'null',
          },
        ],
      },
      configuration: {
        $ref: '#/components/schemas/VisualAnalysisConfigurationResponse',
      },
      created_at: {
        format: 'date-time',
        type: 'string',
      },
      damage_level: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      kind: {
        type: 'string',
      },
      modality: {
        const: 'image',
        type: 'string',
      },
      observation_id: {
        type: 'string',
      },
      physical_event_id: {
        type: 'string',
      },
      question: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      safety_rule_ids: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
      status: {
        type: 'string',
      },
      truth_status: {
        const: 'analytical',
        type: 'string',
      },
      uncertainty: {
        type: 'string',
      },
      visual_cues: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
    },
    required: [
      'observation_id',
      'asset_id',
      'association_id',
      'physical_event_id',
      'modality',
      'truth_status',
      'kind',
      'status',
      'uncertainty',
      'configuration',
      'created_at',
    ],
    type: 'object',
  },
} as const;

export type ApiSchemaName = keyof typeof apiSchemas;

export function matchesApiSchema(name: ApiSchemaName, value: unknown): boolean {
  return matchesOpenApiSchema(value, apiSchemas[name], apiSchemas);
}

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
