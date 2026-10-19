// Generated from the DisasterMonitor backend OpenAPI schema.
// Run `npm run generate:api-contract` after backend schema changes.

import { matchesOpenApiSchema } from '@/shared/api/openapiSchema';

const apiSchemas = {
  AcquisitionAudit: {
    properties: {
      article_attempts: {
        type: 'integer',
      },
      article_failures: {
        type: 'integer',
      },
      budget_excluded: {
        type: 'integer',
      },
      duplicate_urls: {
        type: 'integer',
      },
      invalid_leads: {
        type: 'integer',
      },
      leads_received: {
        type: 'integer',
      },
      partition: {
        type: 'string',
      },
      provider: {
        type: 'string',
      },
    },
    required: ['provider', 'partition'],
    type: 'object',
  },
  ActiveIncidentCountryResponse: {
    properties: {
      association_basis: {
        enum: [
          'coordinate_polygon',
          'source_mention',
          'named_region',
          'nearby_boundary',
        ],
        type: 'string',
      },
      code: {
        maxLength: 3,
        minLength: 3,
        type: 'string',
      },
      distance_km: {
        anyOf: [
          {
            minimum: 0,
            type: 'number',
          },
          {
            type: 'null',
          },
        ],
      },
      name: {
        minLength: 1,
        type: 'string',
      },
    },
    required: ['code', 'name', 'association_basis'],
    type: 'object',
  },
  ActiveIncidentResponse: {
    properties: {
      activity_status: {
        $ref: '#/components/schemas/IncidentActivityStatus',
      },
      association_reasons: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
      collection_notices: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
      country: {
        anyOf: [
          {
            $ref: '#/components/schemas/ActiveIncidentCountryResponse',
          },
          {
            type: 'null',
          },
        ],
      },
      detection: {
        $ref: '#/components/schemas/IncidentDetectionTimelineResponse',
      },
      disaster: {
        $ref: '#/components/schemas/Disaster',
      },
      discovery_reports: {
        items: {
          $ref: '#/components/schemas/DiscoveryReportResponse',
        },
        type: 'array',
      },
      event_id: {
        type: 'string',
      },
      event_time: {
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
      event_time_basis: {
        enum: ['reported', 'unknown'],
        type: 'string',
      },
      event_time_end: {
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
      event_time_precision: {
        $ref: '#/components/schemas/EventTimePrecision',
      },
      evidence_sources: {
        items: {
          $ref: '#/components/schemas/SourceResponse',
        },
        type: 'array',
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
      identity_status: {
        anyOf: [
          {
            enum: ['candidate', 'associated'],
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      independent_origins: {
        anyOf: [
          {
            type: 'integer',
          },
          {
            type: 'null',
          },
        ],
      },
      last_meaningful_change_at: {
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
      lineage_ids: {
        items: {
          type: 'string',
        },
        type: 'array',
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
      observation_kind: {
        enum: ['physical_event', 'preliminary_event', 'acquisition'],
        type: 'string',
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
      provider_ids: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
      provider_tier: {
        $ref: '#/components/schemas/ProviderTier',
      },
      source: {
        $ref: '#/components/schemas/SourceResponse',
      },
      source_authority: {
        $ref: '#/components/schemas/SourceAuthority',
      },
      verification_status: {
        enum: ['provisional_news_detected', 'source_backed', 'rejected'],
        type: 'string',
      },
    },
    required: [
      'event_id',
      'disaster',
      'location',
      'event_time',
      'provider_tier',
      'source_authority',
      'source',
    ],
    type: 'object',
  },
  ActiveIncidentsSnapshotResponse: {
    properties: {
      correlations: {
        items: {
          $ref: '#/components/schemas/CompoundHazardCorrelationResponse',
        },
        type: 'array',
      },
      coverage: {
        items: {
          $ref: '#/components/schemas/DisasterIncidentCoverageResponse',
        },
        type: 'array',
      },
      has_more: {
        type: 'boolean',
      },
      historical_limitations: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
      incidents: {
        items: {
          $ref: '#/components/schemas/ActiveIncidentResponse',
        },
        type: 'array',
      },
      is_stale: {
        type: 'boolean',
      },
      next_cursor: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      observations: {
        items: {
          $ref: '#/components/schemas/ActiveIncidentResponse',
        },
        type: 'array',
      },
      refresh_state: {
        enum: ['fresh', 'refreshing', 'stale'],
        type: 'string',
      },
      retrieved_at: {
        format: 'date-time',
        type: 'string',
      },
      snapshot_version: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      total_incident_count: {
        anyOf: [
          {
            type: 'integer',
          },
          {
            type: 'null',
          },
        ],
      },
      warnings: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
    },
    required: ['retrieved_at'],
    type: 'object',
  },
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
      claims: {
        items: {
          $ref: '#/components/schemas/EvidenceClaimResponse',
        },
        type: 'array',
      },
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
      investigation_case: {
        anyOf: [
          {
            $ref: '#/components/schemas/InvestigationCaseResponse',
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
      operator_actions: {
        items: {
          oneOf: [
            {
              $ref: '#/components/schemas/OpenPanelOperatorActionResponse',
            },
            {
              $ref: '#/components/schemas/SetTimeWindowOperatorActionResponse',
            },
            {
              $ref: '#/components/schemas/ShowLayerOperatorActionResponse',
            },
            {
              $ref: '#/components/schemas/CreateIncidentWatchOperatorActionResponse',
            },
          ],
        },
        type: 'array',
      },
      original_message: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      partial: {
        type: 'boolean',
      },
      response_language: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
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
      timeline: {
        items: {
          $ref: '#/components/schemas/EvidenceTimelineEntryResponse',
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
  AssociatedWarning: {
    properties: {
      alert: {
        $ref: '#/components/schemas/CapAlert',
      },
      association: {
        $ref: '#/components/schemas/WarningAssociation',
      },
    },
    required: ['alert', 'association'],
    type: 'object',
  },
  BaselineVulnerabilityContext: {
    properties: {
      aggregation_level: {
        type: 'string',
      },
      context_role: {
        type: 'string',
      },
      coping_capacity_index: {
        type: 'number',
      },
      dataset_version: {
        type: 'string',
      },
      interpretation: {
        type: 'string',
      },
      place_code: {
        type: 'string',
      },
      place_name: {
        type: 'string',
      },
      risk_index: {
        type: 'number',
      },
      source_id: {
        type: 'string',
      },
      vintage: {
        type: 'integer',
      },
      vulnerability_index: {
        type: 'number',
      },
    },
    required: [
      'place_code',
      'place_name',
      'aggregation_level',
      'dataset_version',
      'vintage',
      'risk_index',
      'vulnerability_index',
      'coping_capacity_index',
      'source_id',
      'context_role',
      'interpretation',
    ],
    type: 'object',
  },
  CapAlert: {
    properties: {
      addresses: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
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
      codes: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
      identifier: {
        type: 'string',
      },
      incidents: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
      infos: {
        items: {
          $ref: '#/components/schemas/CapInfo',
        },
        type: 'array',
      },
      limitations: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
      message_type: {
        $ref: '#/components/schemas/CapMessageType',
      },
      note: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      profile: {
        anyOf: [
          {
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
      references: {
        items: {
          $ref: '#/components/schemas/CapMessageReference',
        },
        type: 'array',
      },
      restriction: {
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
      scope: {
        $ref: '#/components/schemas/CapScope',
      },
      sender: {
        type: 'string',
      },
      sent: {
        format: 'date-time',
        type: 'string',
      },
      signature_present: {
        type: 'boolean',
      },
      signature_verified: {
        anyOf: [
          {
            type: 'boolean',
          },
          {
            type: 'null',
          },
        ],
      },
      source: {
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
      status: {
        $ref: '#/components/schemas/CapStatus',
      },
    },
    required: [
      'identifier',
      'sender',
      'sent',
      'status',
      'message_type',
      'scope',
      'source_id',
      'publisher',
      'infos',
      'retrieved_at',
      'attribution',
      'limitations',
    ],
    type: 'object',
  },
  CapArea: {
    properties: {
      altitude_m: {
        anyOf: [
          {
            type: 'number',
          },
          {
            type: 'null',
          },
        ],
      },
      ceiling_m: {
        anyOf: [
          {
            type: 'number',
          },
          {
            type: 'null',
          },
        ],
      },
      circles: {
        items: {
          $ref: '#/components/schemas/CapCircle',
        },
        type: 'array',
      },
      description: {
        type: 'string',
      },
      geocodes: {
        items: {
          maxItems: 2,
          minItems: 2,
          prefixItems: [
            {
              type: 'string',
            },
            {
              type: 'string',
            },
          ],
          type: 'array',
        },
        type: 'array',
      },
      polygons: {
        items: {
          $ref: '#/components/schemas/MultiPolygon',
        },
        type: 'array',
      },
    },
    required: ['description'],
    type: 'object',
  },
  CapCircle: {
    properties: {
      center: {
        $ref: '#/components/schemas/Coordinate',
      },
      radius_km: {
        type: 'number',
      },
    },
    required: ['center', 'radius_km'],
    type: 'object',
  },
  CapInfo: {
    properties: {
      areas: {
        items: {
          $ref: '#/components/schemas/CapArea',
        },
        type: 'array',
      },
      categories: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
      certainty: {
        $ref: '#/components/schemas/WarningCertainty',
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
      effective: {
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
      event: {
        type: 'string',
      },
      event_codes: {
        items: {
          maxItems: 2,
          minItems: 2,
          prefixItems: [
            {
              type: 'string',
            },
            {
              type: 'string',
            },
          ],
          type: 'array',
        },
        type: 'array',
      },
      expires: {
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
      headline: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      instruction: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      language: {
        type: 'string',
      },
      onset: {
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
      parameters: {
        items: {
          maxItems: 2,
          minItems: 2,
          prefixItems: [
            {
              type: 'string',
            },
            {
              type: 'string',
            },
          ],
          type: 'array',
        },
        type: 'array',
      },
      sender_name: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      severity: {
        $ref: '#/components/schemas/WarningSeverity',
      },
      urgency: {
        $ref: '#/components/schemas/WarningUrgency',
      },
    },
    required: [
      'language',
      'categories',
      'event',
      'event_codes',
      'urgency',
      'severity',
      'certainty',
      'effective',
      'onset',
      'expires',
      'sender_name',
      'headline',
      'description',
      'instruction',
      'areas',
    ],
    type: 'object',
  },
  CapMessageReference: {
    properties: {
      identifier: {
        type: 'string',
      },
      sender: {
        type: 'string',
      },
      sent: {
        format: 'date-time',
        type: 'string',
      },
    },
    required: ['sender', 'identifier', 'sent'],
    type: 'object',
  },
  CapMessageType: {
    enum: ['alert', 'update', 'cancel', 'ack', 'error'],
    type: 'string',
  },
  CapScope: {
    enum: ['public', 'restricted', 'private'],
    type: 'string',
  },
  CapStatus: {
    enum: ['actual', 'exercise', 'system', 'test', 'draft'],
    type: 'string',
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
  CompoundHazardCorrelationResponse: {
    properties: {
      correlation_id: {
        type: 'string',
      },
      distance_km: {
        minimum: 0,
        type: 'number',
      },
      first_disaster: {
        $ref: '#/components/schemas/Disaster',
      },
      first_event_id: {
        type: 'string',
      },
      first_physical_event_id: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      limitation: {
        type: 'string',
      },
      relationship: {
        const: 'spatiotemporal_association',
        type: 'string',
      },
      rule_id: {
        type: 'string',
      },
      second_disaster: {
        $ref: '#/components/schemas/Disaster',
      },
      second_event_id: {
        type: 'string',
      },
      second_physical_event_id: {
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
      summary: {
        type: 'string',
      },
      time_delta_seconds: {
        minimum: 0,
        type: 'integer',
      },
    },
    required: [
      'correlation_id',
      'rule_id',
      'relationship',
      'first_event_id',
      'first_disaster',
      'second_event_id',
      'second_disaster',
      'distance_km',
      'time_delta_seconds',
      'summary',
      'limitation',
    ],
    type: 'object',
  },
  ContextAvailability: {
    enum: ['available', 'partial', 'no_data', 'unavailable'],
    type: 'string',
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
  Coordinate: {
    properties: {
      latitude: {
        type: 'number',
      },
      longitude: {
        type: 'number',
      },
    },
    required: ['latitude', 'longitude'],
    type: 'object',
  },
  CreateIncidentWatchOperatorActionResponse: {
    additionalProperties: false,
    properties: {
      action_id: {
        type: 'string',
      },
      action_type: {
        const: 'create_incident_watch',
        type: 'string',
      },
      disaster: {
        $ref: '#/components/schemas/Disaster',
      },
      label: {
        maxLength: 200,
        minLength: 1,
        type: 'string',
      },
      refresh_interval_seconds: {
        enum: [900, 1800, 3600, 21600, 86400],
        type: 'integer',
      },
      risk: {
        const: 'confirmation_required',
        type: 'string',
      },
      scope: {
        $ref: '#/components/schemas/OperatorActionScopeResponse',
      },
    },
    required: [
      'action_id',
      'action_type',
      'risk',
      'disaster',
      'scope',
      'refresh_interval_seconds',
      'label',
    ],
    type: 'object',
  },
  CrossHazardAssessmentResponse: {
    properties: {
      limitation: {
        type: 'string',
      },
      status: {
        enum: [
          'associated',
          'not_established',
          'unsupported_pair',
          'insufficient_evidence',
        ],
        type: 'string',
      },
      summary: {
        type: 'string',
      },
    },
    required: ['status', 'summary', 'limitation'],
    type: 'object',
  },
  CycloneMapCoordinate: {
    properties: {
      latitude: {
        type: 'number',
      },
      longitude: {
        type: 'number',
      },
      valid_at: {
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
    required: ['latitude', 'longitude'],
    type: 'object',
  },
  CycloneMapCoordinateResponse: {
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
      valid_at: {
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
    required: ['latitude', 'longitude'],
    type: 'object',
  },
  CycloneMapGeometryKind: {
    enum: ['point', 'track', 'area'],
    type: 'string',
  },
  CycloneMapLayer: {
    properties: {
      coordinates: {
        items: {
          $ref: '#/components/schemas/CycloneMapCoordinate',
        },
        type: 'array',
      },
      geometry_kind: {
        $ref: '#/components/schemas/CycloneMapGeometryKind',
      },
      issued_at: {
        format: 'date-time',
        type: 'string',
      },
      layer_id: {
        type: 'string',
      },
      limitation: {
        type: 'string',
      },
      provisional: {
        type: 'boolean',
      },
      reconciliation: {
        type: 'string',
      },
      semantic_role: {
        $ref: '#/components/schemas/CycloneMapSemanticRole',
      },
      source: {
        $ref: '#/components/schemas/SourceReference',
      },
      storm_id: {
        type: 'string',
      },
      valid_from: {
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
      valid_to: {
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
      wind_threshold: {
        anyOf: [
          {
            type: 'number',
          },
          {
            type: 'null',
          },
        ],
      },
      wind_threshold_unit: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
    },
    required: [
      'layer_id',
      'semantic_role',
      'geometry_kind',
      'coordinates',
      'source',
      'issued_at',
      'valid_from',
      'valid_to',
      'storm_id',
      'provisional',
      'limitation',
      'reconciliation',
    ],
    type: 'object',
  },
  CycloneMapLayerResponse: {
    properties: {
      coordinates: {
        items: {
          $ref: '#/components/schemas/CycloneMapCoordinateResponse',
        },
        type: 'array',
      },
      geometry_kind: {
        enum: ['point', 'track', 'area'],
        type: 'string',
      },
      issued_at: {
        format: 'date-time',
        type: 'string',
      },
      layer_id: {
        type: 'string',
      },
      limitation: {
        type: 'string',
      },
      provisional: {
        type: 'boolean',
      },
      reconciliation: {
        type: 'string',
      },
      semantic_role: {
        enum: ['provisional_track', 'forecast_track', 'uncertainty_area', 'wind_radii'],
        type: 'string',
      },
      source: {
        $ref: '#/components/schemas/SourceResponse',
      },
      storm_id: {
        type: 'string',
      },
      valid_from: {
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
      valid_to: {
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
      wind_threshold: {
        anyOf: [
          {
            type: 'number',
          },
          {
            type: 'null',
          },
        ],
      },
      wind_threshold_unit: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
    },
    required: [
      'layer_id',
      'semantic_role',
      'geometry_kind',
      'coordinates',
      'source',
      'issued_at',
      'storm_id',
      'provisional',
      'limitation',
      'reconciliation',
    ],
    type: 'object',
  },
  CycloneMapSemanticRole: {
    enum: ['provisional_track', 'forecast_track', 'uncertainty_area', 'wind_radii'],
    type: 'string',
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
  Disaster: {
    enum: [
      'earthquake',
      'flood',
      'wildfire',
      'landslide',
      'tropical_cyclone',
      'volcanic_eruption',
      'drought',
    ],
    type: 'string',
  },
  DisasterIncidentCoverageResponse: {
    properties: {
      detail: {
        type: 'string',
      },
      disaster: {
        $ref: '#/components/schemas/Disaster',
      },
      incident_count: {
        type: 'integer',
      },
      providers: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
      records_seen: {
        type: 'integer',
      },
      scan_complete: {
        type: 'boolean',
      },
      state: {
        enum: ['events_found', 'no_matching_records', 'degraded', 'unavailable'],
        type: 'string',
      },
      truncated: {
        type: 'boolean',
      },
    },
    required: ['disaster', 'state', 'incident_count', 'detail'],
    type: 'object',
  },
  DisasterMediaGallery: {
    properties: {
      candidate_count: {
        type: 'integer',
      },
      collection_limit: {
        type: 'integer',
      },
      event_id: {
        type: 'string',
      },
      generated_at: {
        format: 'date-time',
        type: 'string',
      },
      items: {
        items: {
          $ref: '#/components/schemas/DisasterMediaItem',
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
      rejection_reasons: {
        items: {
          maxItems: 2,
          minItems: 2,
          prefixItems: [
            {
              type: 'string',
            },
            {
              type: 'integer',
            },
          ],
          type: 'array',
        },
        type: 'array',
      },
      source_articles: {
        items: {
          $ref: '#/components/schemas/SourceReference',
        },
        type: 'array',
      },
      truncated: {
        type: 'boolean',
      },
      unavailable_sources: {
        items: {
          $ref: '#/components/schemas/MediaUnavailableSource',
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
    required: [
      'event_id',
      'physical_event_id',
      'generated_at',
      'items',
      'rejected_count',
      'provider_ids',
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
  DisasterMediaItem: {
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
        $ref: '#/components/schemas/MediaAssociationStatus',
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
        $ref: '#/components/schemas/MediaCreditKind',
      },
      event_id: {
        type: 'string',
      },
      height: {
        type: 'integer',
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
      rights_status: {
        $ref: '#/components/schemas/MediaRightsStatus',
      },
      role: {
        $ref: '#/components/schemas/MediaContentRole',
      },
      source_id: {
        type: 'string',
      },
      source_page_url: {
        type: 'string',
      },
      source_references: {
        items: {
          $ref: '#/components/schemas/MediaSourceAttribution',
        },
        type: 'array',
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
      'event_id',
      'physical_event_id',
      'source_id',
      'publisher',
      'source_page_url',
      'caption',
      'credit',
      'credit_kind',
      'published_at',
      'captured_at',
      'license_name',
      'license_url',
      'rights_status',
      'role',
      'association_status',
      'association_rule_ids',
      'association_detail',
      'uncertainty',
      'content_sha256',
      'width',
      'height',
    ],
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
  DiscoveryReportResponse: {
    properties: {
      access_issue: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      claims: {
        items: {
          $ref: '#/components/schemas/ReportedImpactResponse',
        },
        type: 'array',
      },
      event_date_end: {
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
      event_date_precision: {
        enum: ['exact', 'day', 'range', 'unknown'],
        type: 'string',
      },
      event_date_wording: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      event_time: {
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
      event_year_inferred: {
        type: 'boolean',
      },
      fatality_evidence: {
        items: {
          type: 'string',
        },
        type: 'array',
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
      indexed_at: {
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
      location: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      location_precision: {
        enum: ['named_place', 'country_context', 'unresolved'],
        type: 'string',
      },
      mention_excerpt: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      mention_id: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      mention_notices: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
      mention_role: {
        enum: ['reported', 'ongoing', 'historical', 'forecast', 'uncertain'],
        type: 'string',
      },
      origin: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      original_url: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      source: {
        $ref: '#/components/schemas/SourceResponse',
      },
    },
    required: ['source'],
    type: 'object',
  },
  DiscoveryScanResponse: {
    properties: {
      acquisition: {
        items: {
          $ref: '#/components/schemas/AcquisitionAudit',
        },
        type: 'array',
      },
      assessment_counts: {
        additionalProperties: {
          type: 'integer',
        },
        type: 'object',
      },
      associated_event_count: {
        type: 'integer',
      },
      candidate_count: {
        type: 'integer',
      },
      coverage_notice: {
        type: 'string',
      },
      failed_operations: {
        type: 'integer',
      },
      finished_at: {
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
      interval_end: {
        format: 'date-time',
        type: 'string',
      },
      interval_start: {
        format: 'date-time',
        type: 'string',
      },
      issues: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
      reporting_days: {
        type: 'integer',
      },
      reports_seen: {
        type: 'integer',
      },
      reprocessed_from: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      scan_id: {
        type: 'string',
      },
      snapshot: {
        $ref: '#/components/schemas/ActiveIncidentsSnapshotResponse',
      },
      status: {
        enum: ['running', 'completed', 'incomplete', 'failed'],
        type: 'string',
      },
      successful_operations: {
        type: 'integer',
      },
      truncated: {
        type: 'boolean',
      },
      uncertain_publication_count: {
        type: 'integer',
      },
      unknown_publication_count: {
        type: 'integer',
      },
      unlocated_count: {
        type: 'integer',
      },
    },
    required: [
      'scan_id',
      'reporting_days',
      'interval_start',
      'interval_end',
      'status',
      'finished_at',
      'issues',
      'truncated',
      'reports_seen',
      'unknown_publication_count',
      'unlocated_count',
      'successful_operations',
      'failed_operations',
      'snapshot',
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
  EventTimePrecision: {
    enum: ['exact', 'day', 'week'],
    type: 'string',
  },
  EvidenceClaimResponse: {
    additionalProperties: false,
    properties: {
      alternatives: {
        items: {
          $ref: '#/components/schemas/EvidenceClaimVariantResponse',
        },
        type: 'array',
      },
      claim_id: {
        type: 'string',
      },
      claim_key: {
        type: 'string',
      },
      contradictions: {
        items: {
          $ref: '#/components/schemas/EvidenceClaimVariantResponse',
        },
        type: 'array',
      },
      disposition: {
        anyOf: [
          {
            $ref: '#/components/schemas/EvidenceDisposition',
          },
          {
            type: 'null',
          },
        ],
      },
      gap: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      label: {
        type: 'string',
      },
      observed_at: {
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
      retrieved_at: {
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
      source: {
        anyOf: [
          {
            $ref: '#/components/schemas/SourceResponse',
          },
          {
            type: 'null',
          },
        ],
      },
      status: {
        $ref: '#/components/schemas/FactStatus',
      },
      value: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      why: {
        type: 'string',
      },
    },
    required: [
      'claim_id',
      'claim_key',
      'label',
      'value',
      'status',
      'disposition',
      'why',
      'source',
    ],
    type: 'object',
  },
  EvidenceClaimVariantResponse: {
    additionalProperties: false,
    properties: {
      disposition: {
        $ref: '#/components/schemas/EvidenceDisposition',
      },
      observation_id: {
        type: 'string',
      },
      observed_at: {
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
      retrieved_at: {
        format: 'date-time',
        type: 'string',
      },
      rule_id: {
        type: 'string',
      },
      source: {
        $ref: '#/components/schemas/SourceResponse',
      },
      status: {
        $ref: '#/components/schemas/FactStatus',
      },
      value: {
        type: 'string',
      },
    },
    required: [
      'observation_id',
      'value',
      'status',
      'disposition',
      'source',
      'retrieved_at',
      'rule_id',
    ],
    type: 'object',
  },
  EvidenceDisposition: {
    enum: ['current', 'superseded', 'conflicting', 'duplicate', 'unusable'],
    type: 'string',
  },
  EvidenceTimelineEntryResponse: {
    additionalProperties: false,
    properties: {
      claim_key: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      detail: {
        type: 'string',
      },
      entry_id: {
        type: 'string',
      },
      event_type: {
        $ref: '#/components/schemas/EvidenceTimelineEventType',
      },
      occurred_at: {
        format: 'date-time',
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
      related_id: {
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
      source: {
        anyOf: [
          {
            $ref: '#/components/schemas/SourceResponse',
          },
          {
            type: 'null',
          },
        ],
      },
      status: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      title: {
        type: 'string',
      },
    },
    required: ['entry_id', 'event_type', 'occurred_at', 'title', 'detail', 'source'],
    type: 'object',
  },
  EvidenceTimelineEventType: {
    enum: [
      'normalized_observation',
      'coverage_status',
      'warning_lifecycle',
      'situation_report',
      'imagery_acquisition',
      'imagery_selection',
      'watch_change',
      'claim_reconciliation',
    ],
    type: 'string',
  },
  ExposureAnalysis: {
    properties: {
      assets: {
        items: {
          $ref: '#/components/schemas/InfrastructureAsset',
        },
        type: 'array',
      },
      calculated_at: {
        format: 'date-time',
        type: 'string',
      },
      display_label: {
        type: 'string',
      },
      geometry: {
        $ref: '#/components/schemas/ExposureGeometry',
      },
      limitations: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
      osm_completeness: {
        anyOf: [
          {
            $ref: '#/components/schemas/OsmCompletenessIndicator',
          },
          {
            type: 'null',
          },
        ],
      },
      population_disagreement: {
        anyOf: [
          {
            $ref: '#/components/schemas/PopulationDisagreement',
          },
          {
            type: 'null',
          },
        ],
      },
      population_estimates: {
        items: {
          $ref: '#/components/schemas/PopulationExposureEstimate',
        },
        type: 'array',
      },
    },
    required: [
      'geometry',
      'population_estimates',
      'assets',
      'population_disagreement',
      'display_label',
      'calculated_at',
      'limitations',
    ],
    type: 'object',
  },
  ExposureDataset: {
    properties: {
      dataset_id: {
        type: 'string',
      },
      license_name: {
        type: 'string',
      },
      publisher: {
        type: 'string',
      },
      resolution_m: {
        type: 'number',
      },
      role: {
        $ref: '#/components/schemas/ExposureDatasetRole',
      },
      source_url: {
        type: 'string',
      },
      uncertainty: {
        type: 'string',
      },
      version: {
        type: 'string',
      },
      vintage: {
        type: 'integer',
      },
    },
    required: [
      'dataset_id',
      'publisher',
      'version',
      'vintage',
      'resolution_m',
      'license_name',
      'source_url',
      'role',
      'uncertainty',
    ],
    type: 'object',
  },
  ExposureDatasetRole: {
    enum: ['primary', 'secondary'],
    type: 'string',
  },
  ExposureGeometry: {
    properties: {
      geometry: {
        $ref: '#/components/schemas/MultiPolygon',
      },
      observed_at: {
        format: 'date-time',
        type: 'string',
      },
      role: {
        $ref: '#/components/schemas/ExposureGeometryRole',
      },
      source_id: {
        type: 'string',
      },
      source_version: {
        type: 'string',
      },
    },
    required: ['geometry', 'role', 'source_id', 'source_version', 'observed_at'],
    type: 'object',
  },
  ExposureGeometryRole: {
    enum: [
      'operator_inspection',
      'mapped_hazard',
      'forecast_hazard',
      'modelled_hazard',
    ],
    type: 'string',
  },
  FactStatus: {
    enum: ['confirmed', 'preliminary', 'estimated', 'disputed', 'unknown'],
    type: 'string',
  },
  GroundImageryArtifactResponse: {
    properties: {
      artifact_id: {
        type: 'string',
      },
      byte_count: {
        type: 'integer',
      },
      content_type: {
        type: 'string',
      },
      created_at: {
        format: 'date-time',
        type: 'string',
      },
      grid: {
        $ref: '#/components/schemas/GroundImageryGridResponse',
      },
      observation: {
        anyOf: [
          {
            $ref: '#/components/schemas/GroundImageryObservationResponse',
          },
          {
            type: 'null',
          },
        ],
      },
      output_kind: {
        type: 'string',
      },
      role: {
        type: 'string',
      },
      selection_id: {
        type: 'string',
      },
      sensor: {
        $ref: '#/components/schemas/Sensor',
      },
      sha256: {
        type: 'string',
      },
      source_product_ids: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
      storage_key: {
        type: 'string',
      },
    },
    required: [
      'artifact_id',
      'selection_id',
      'sensor',
      'role',
      'output_kind',
      'content_type',
      'storage_key',
      'byte_count',
      'sha256',
      'source_product_ids',
      'grid',
      'created_at',
    ],
    type: 'object',
  },
  GroundImageryGridResponse: {
    properties: {
      crs: {
        type: 'string',
      },
      height: {
        type: 'integer',
      },
      max_x: {
        type: 'number',
      },
      max_y: {
        type: 'number',
      },
      min_x: {
        type: 'number',
      },
      min_y: {
        type: 'number',
      },
      pixel_size_m: {
        type: 'number',
      },
      resolution_label: {
        type: 'string',
      },
      width: {
        type: 'integer',
      },
    },
    required: [
      'crs',
      'min_x',
      'min_y',
      'max_x',
      'max_y',
      'pixel_size_m',
      'width',
      'height',
      'resolution_label',
    ],
    type: 'object',
  },
  GroundImageryJobResponse: {
    properties: {
      attempt: {
        type: 'integer',
      },
      claimed_at: {
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
      diagnostic: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      error_code: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      fencing_token: {
        type: 'integer',
      },
      job_id: {
        type: 'string',
      },
      lease_expires_at: {
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
      max_attempts: {
        type: 'integer',
      },
      next_attempt_at: {
        format: 'date-time',
        type: 'string',
      },
      request_version: {
        type: 'integer',
      },
      role: {
        type: 'string',
      },
      sensor: {
        $ref: '#/components/schemas/Sensor',
      },
      status: {
        type: 'string',
      },
    },
    required: [
      'job_id',
      'request_version',
      'sensor',
      'role',
      'status',
      'attempt',
      'max_attempts',
      'next_attempt_at',
      'fencing_token',
    ],
    type: 'object',
  },
  GroundImageryManifestResponse: {
    properties: {
      artifacts: {
        items: {
          additionalProperties: true,
          type: 'object',
        },
        type: 'array',
      },
      disaster: {
        type: 'string',
      },
      incident_id: {
        type: 'string',
      },
      manifest_version: {
        type: 'string',
      },
      observations: {
        items: {
          additionalProperties: true,
          type: 'object',
        },
        type: 'array',
      },
      onset: {
        anyOf: [
          {
            additionalProperties: true,
            type: 'object',
          },
          {
            type: 'null',
          },
        ],
      },
      reason_codes: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
      reference_time: {
        type: 'string',
      },
      region: {
        anyOf: [
          {
            additionalProperties: true,
            type: 'object',
          },
          {
            type: 'null',
          },
        ],
      },
      request_id: {
        type: 'string',
      },
      request_version: {
        type: 'integer',
      },
      selections: {
        items: {
          additionalProperties: true,
          type: 'object',
        },
        type: 'array',
      },
      state: {
        type: 'string',
      },
      temporal_policy_version: {
        type: 'string',
      },
    },
    required: [
      'manifest_version',
      'request_id',
      'request_version',
      'incident_id',
      'disaster',
      'region',
      'temporal_policy_version',
      'reference_time',
      'onset',
      'state',
      'reason_codes',
      'observations',
      'selections',
    ],
    type: 'object',
  },
  GroundImageryObservationResponse: {
    properties: {
      acquisition_id: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      captured_end: {
        format: 'date-time',
        type: 'string',
      },
      captured_start: {
        format: 'date-time',
        type: 'string',
      },
      cloud_cover_fraction: {
        anyOf: [
          {
            type: 'number',
          },
          {
            type: 'null',
          },
        ],
      },
      footprint: {
        additionalProperties: true,
        type: 'object',
      },
      mode: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      observation_id: {
        type: 'string',
      },
      orbit_direction: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      platform: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      polarizations: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
      product_id: {
        type: 'string',
      },
      quality: {
        anyOf: [
          {
            $ref: '#/components/schemas/GroundImageryQualityResponse',
          },
          {
            type: 'null',
          },
        ],
      },
      readiness: {
        type: 'string',
      },
      relative_orbit: {
        anyOf: [
          {
            type: 'integer',
          },
          {
            type: 'null',
          },
        ],
      },
      revision: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      sensor: {
        $ref: '#/components/schemas/Sensor',
      },
      source_url: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
    },
    required: [
      'observation_id',
      'sensor',
      'product_id',
      'acquisition_id',
      'revision',
      'platform',
      'captured_start',
      'captured_end',
      'readiness',
      'footprint',
      'mode',
      'relative_orbit',
      'orbit_direction',
      'polarizations',
      'cloud_cover_fraction',
      'quality',
      'source_url',
    ],
    type: 'object',
  },
  GroundImageryQualityResponse: {
    properties: {
      component_usable_fractions: {
        additionalProperties: {
          type: 'number',
        },
        type: 'object',
      },
      covered_fraction: {
        type: 'number',
      },
      mask_definition: {
        type: 'string',
      },
      obscured_fraction: {
        type: 'number',
      },
      quality_state: {
        type: 'string',
      },
      uncertain_fraction: {
        type: 'number',
      },
      uncovered_fraction: {
        type: 'number',
      },
      usable_fraction: {
        type: 'number',
      },
    },
    required: [
      'covered_fraction',
      'usable_fraction',
      'obscured_fraction',
      'uncertain_fraction',
      'uncovered_fraction',
      'component_usable_fractions',
      'quality_state',
      'mask_definition',
    ],
    type: 'object',
  },
  GroundImageryReadinessResponse: {
    properties: {
      detail: {
        type: 'string',
      },
      state: {
        type: 'string',
      },
    },
    required: ['state', 'detail'],
    type: 'object',
  },
  GroundImageryRegionResolutionResponse: {
    properties: {
      alternatives: {
        items: {
          additionalProperties: true,
          type: 'object',
        },
        type: 'array',
      },
      reason_code: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      region: {
        anyOf: [
          {
            $ref: '#/components/schemas/GroundImageryRegionResponse',
          },
          {
            type: 'null',
          },
        ],
      },
      state: {
        enum: ['resolved', 'ambiguous', 'needs_region'],
        type: 'string',
      },
      warnings: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
    },
    required: ['state', 'region'],
    type: 'object',
  },
  GroundImageryRegionResponse: {
    properties: {
      association: {
        type: 'string',
      },
      core: {
        additionalProperties: true,
        type: 'object',
      },
      geometry_hash: {
        type: 'string',
      },
      inspection: {
        additionalProperties: true,
        type: 'object',
      },
      region_id: {
        type: 'string',
      },
      source_footprints: {
        items: {
          additionalProperties: true,
          type: 'object',
        },
        type: 'array',
      },
      version: {
        type: 'integer',
      },
    },
    required: [
      'region_id',
      'version',
      'geometry_hash',
      'association',
      'core',
      'inspection',
      'source_footprints',
    ],
    type: 'object',
  },
  GroundImageryRequestResponse: {
    properties: {
      artifacts: {
        items: {
          $ref: '#/components/schemas/GroundImageryArtifactResponse',
        },
        type: 'array',
      },
      disaster: {
        type: 'string',
      },
      incident_id: {
        type: 'string',
      },
      jobs: {
        items: {
          $ref: '#/components/schemas/GroundImageryJobResponse',
        },
        type: 'array',
      },
      next_check_at: {
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
      reason_codes: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
      reference_time: {
        format: 'date-time',
        type: 'string',
      },
      region: {
        $ref: '#/components/schemas/GroundImageryRegionResolutionResponse',
      },
      request_id: {
        type: 'string',
      },
      request_version: {
        type: 'integer',
      },
      sensors: {
        items: {
          $ref: '#/components/schemas/GroundImagerySensorStatusResponse',
        },
        type: 'array',
      },
      state: {
        type: 'string',
      },
      temporal_plan: {
        $ref: '#/components/schemas/GroundImageryTemporalPlanResponse',
      },
      watch_enabled: {
        type: 'boolean',
      },
      watch_interval_seconds: {
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
      'request_id',
      'request_version',
      'incident_id',
      'disaster',
      'state',
      'reason_codes',
      'reference_time',
      'region',
      'temporal_plan',
      'sensors',
    ],
    type: 'object',
  },
  GroundImagerySelectionResponse: {
    properties: {
      age_class: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      alternative_observation_ids: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
      explanation: {
        type: 'string',
      },
      label: {
        type: 'string',
      },
      observation: {
        anyOf: [
          {
            $ref: '#/components/schemas/GroundImageryObservationResponse',
          },
          {
            type: 'null',
          },
        ],
      },
      reason: {
        type: 'string',
      },
      role: {
        type: 'string',
      },
      selection_id: {
        type: 'string',
      },
      sensor: {
        $ref: '#/components/schemas/Sensor',
      },
    },
    required: [
      'selection_id',
      'sensor',
      'role',
      'label',
      'observation',
      'reason',
      'explanation',
      'age_class',
      'alternative_observation_ids',
    ],
    type: 'object',
  },
  GroundImagerySensorStatusResponse: {
    properties: {
      failure_code: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      failure_detail: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      next_cursor: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      scan_complete: {
        type: 'boolean',
      },
      scanned_count: {
        type: 'integer',
      },
      selections: {
        items: {
          $ref: '#/components/schemas/GroundImagerySelectionResponse',
        },
        type: 'array',
      },
      sensor: {
        $ref: '#/components/schemas/Sensor',
      },
    },
    required: [
      'sensor',
      'scanned_count',
      'scan_complete',
      'next_cursor',
      'failure_code',
      'failure_detail',
      'selections',
    ],
    type: 'object',
  },
  GroundImageryTemporalPlanResponse: {
    properties: {
      impact_start_earliest: {
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
      impact_start_latest: {
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
      onset_precision: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      onset_source_id: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      policy_version: {
        type: 'string',
      },
      reference_time: {
        format: 'date-time',
        type: 'string',
      },
      windows: {
        items: {
          $ref: '#/components/schemas/GroundImageryTimeWindowResponse',
        },
        type: 'array',
      },
    },
    required: [
      'policy_version',
      'reference_time',
      'impact_start_earliest',
      'impact_start_latest',
      'onset_precision',
      'onset_source_id',
      'windows',
    ],
    type: 'object',
  },
  GroundImageryTimeWindowResponse: {
    properties: {
      end: {
        format: 'date-time',
        type: 'string',
      },
      expanded_end: {
        format: 'date-time',
        type: 'string',
      },
      expanded_start: {
        format: 'date-time',
        type: 'string',
      },
      role: {
        type: 'string',
      },
      sensor: {
        $ref: '#/components/schemas/Sensor',
      },
      start: {
        format: 'date-time',
        type: 'string',
      },
    },
    required: ['role', 'sensor', 'start', 'end', 'expanded_start', 'expanded_end'],
    type: 'object',
  },
  HumanitarianContextSnapshot: {
    properties: {
      availability: {
        $ref: '#/components/schemas/ContextAvailability',
      },
      country_code: {
        type: 'string',
      },
      event_id: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      gaps: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
      indicators: {
        items: {
          $ref: '#/components/schemas/HumanitarianIndicator',
        },
        type: 'array',
      },
      limitations: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
      operational_presence: {
        items: {
          $ref: '#/components/schemas/OperationalPresence',
        },
        type: 'array',
      },
      retrieved_at: {
        format: 'date-time',
        type: 'string',
      },
    },
    required: [
      'country_code',
      'event_id',
      'availability',
      'indicators',
      'operational_presence',
      'retrieved_at',
      'gaps',
      'limitations',
    ],
    type: 'object',
  },
  HumanitarianIndicator: {
    properties: {
      admin1_code: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      admin1_name: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      causal_attribution: {
        type: 'boolean',
      },
      country_code: {
        type: 'string',
      },
      dataset_id: {
        type: 'string',
      },
      dataset_updated_at: {
        format: 'date-time',
        type: 'string',
      },
      dimensions: {
        items: {
          maxItems: 2,
          minItems: 2,
          prefixItems: [
            {
              type: 'string',
            },
            {
              type: 'string',
            },
          ],
          type: 'array',
        },
        type: 'array',
      },
      indicator_id: {
        type: 'string',
      },
      kind: {
        $ref: '#/components/schemas/HumanitarianIndicatorKind',
      },
      license_name: {
        type: 'string',
      },
      reference_period_end: {
        format: 'date-time',
        type: 'string',
      },
      reference_period_start: {
        format: 'date-time',
        type: 'string',
      },
      retrieved_at: {
        format: 'date-time',
        type: 'string',
      },
      source_id: {
        type: 'string',
      },
      source_url: {
        type: 'string',
      },
      stale: {
        type: 'boolean',
      },
      unit: {
        type: 'string',
      },
      value: {
        type: 'number',
      },
    },
    required: [
      'indicator_id',
      'source_id',
      'kind',
      'value',
      'unit',
      'country_code',
      'admin1_code',
      'admin1_name',
      'reference_period_start',
      'reference_period_end',
      'dataset_id',
      'dataset_updated_at',
      'retrieved_at',
      'source_url',
      'license_name',
    ],
    type: 'object',
  },
  HumanitarianIndicatorKind: {
    enum: ['baseline_population', 'displaced_people', 'food_insecurity'],
    type: 'string',
  },
  IncidentActivityStatus: {
    enum: ['ongoing', 'ended', 'unknown'],
    type: 'string',
  },
  IncidentDetectionTimelineResponse: {
    properties: {
      assistant_ready_at: {
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
      candidate_created_at: {
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
      first_observed_at: {
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
      monitor_visible_at: {
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
      news_break_at: {
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
      verified_at: {
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
    type: 'object',
  },
  InfrastructureAsset: {
    properties: {
      asset_id: {
        type: 'string',
      },
      category: {
        $ref: '#/components/schemas/InfrastructureCategory',
      },
      coordinate: {
        anyOf: [
          {
            $ref: '#/components/schemas/Coordinate',
          },
          {
            type: 'null',
          },
        ],
      },
      geometry: {
        anyOf: [
          {
            $ref: '#/components/schemas/MultiPolygon',
          },
          {
            type: 'null',
          },
        ],
      },
      name: {
        type: 'string',
      },
      path: {
        items: {
          $ref: '#/components/schemas/Coordinate',
        },
        type: 'array',
      },
      source_dataset_id: {
        type: 'string',
      },
      source_version: {
        type: 'string',
      },
    },
    required: ['asset_id', 'name', 'category', 'source_dataset_id', 'source_version'],
    type: 'object',
  },
  InfrastructureCategory: {
    enum: [
      'hospital',
      'clinic',
      'school',
      'fire_station',
      'police',
      'bridge',
      'major_road',
      'power',
      'water',
      'shelter',
    ],
    type: 'string',
  },
  InvestigationCaseCountryResponse: {
    properties: {
      country_code: {
        type: 'string',
      },
      country_name: {
        type: 'string',
      },
    },
    required: ['country_code', 'country_name'],
    type: 'object',
  },
  InvestigationCaseResponse: {
    properties: {
      case_id: {
        type: 'string',
      },
      correlations: {
        items: {
          $ref: '#/components/schemas/CompoundHazardCorrelationResponse',
        },
        type: 'array',
      },
      countries: {
        items: {
          $ref: '#/components/schemas/InvestigationCaseCountryResponse',
        },
        maxItems: 4,
        minItems: 1,
        type: 'array',
      },
      country: {
        anyOf: [
          {
            $ref: '#/components/schemas/InvestigationCaseCountryResponse',
          },
          {
            type: 'null',
          },
        ],
      },
      cross_hazard_assessment: {
        $ref: '#/components/schemas/CrossHazardAssessmentResponse',
      },
      partial: {
        type: 'boolean',
      },
      status: {
        enum: ['completed', 'partial'],
        type: 'string',
      },
      targets: {
        items: {
          $ref: '#/components/schemas/InvestigationTargetResponse',
        },
        maxItems: 4,
        minItems: 2,
        type: 'array',
      },
    },
    required: [
      'case_id',
      'countries',
      'status',
      'partial',
      'targets',
      'cross_hazard_assessment',
    ],
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
      event_issue_codes: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
      event_records_seen: {
        type: 'integer',
      },
      event_scan_complete: {
        anyOf: [
          {
            type: 'boolean',
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
      physical_event_count: {
        type: 'integer',
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
      place_candidate_count: {
        type: 'integer',
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
  InvestigationTargetResponse: {
    properties: {
      country_code: {
        type: 'string',
      },
      country_name: {
        type: 'string',
      },
      disaster: {
        $ref: '#/components/schemas/Disaster',
      },
      partial: {
        type: 'boolean',
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
      status: {
        enum: ['completed', 'partial', 'coverage_unavailable', 'failed'],
        type: 'string',
      },
      target_id: {
        type: 'string',
      },
      termination_reason: {
        type: 'string',
      },
      warnings: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
    },
    required: [
      'target_id',
      'disaster',
      'country_code',
      'country_name',
      'status',
      'partial',
      'termination_reason',
    ],
    type: 'object',
  },
  LinearRing: {
    properties: {
      coordinates: {
        items: {
          $ref: '#/components/schemas/Coordinate',
        },
        type: 'array',
      },
    },
    required: ['coordinates'],
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
      'maximum_wind_speed',
      'provider_significance',
      'confidence',
      'fire_radiative_power',
      'burned_area',
      'severity',
    ],
    type: 'string',
  },
  MediaAssociationStatus: {
    enum: ['exact_event_link', 'corroborated', 'rejected'],
    type: 'string',
  },
  MediaContentRole: {
    enum: [
      'aftermath',
      'rescue_effort',
      'relief_operation',
      'scientific_overview',
      'relevant_scene',
    ],
    type: 'string',
  },
  MediaCreditKind: {
    enum: ['photographer', 'agency', 'publisher'],
    type: 'string',
  },
  MediaRightsStatus: {
    enum: ['licensed_reuse', 'source_preview'],
    type: 'string',
  },
  MediaSourceAttribution: {
    properties: {
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
      credit: {
        type: 'string',
      },
      credit_kind: {
        $ref: '#/components/schemas/MediaCreditKind',
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
      rights_status: {
        $ref: '#/components/schemas/MediaRightsStatus',
      },
      source_page_url: {
        type: 'string',
      },
    },
    required: [
      'source_page_url',
      'publisher',
      'caption',
      'credit',
      'credit_kind',
      'published_at',
      'captured_at',
      'rights_status',
    ],
    type: 'object',
  },
  MediaUnavailableSource: {
    properties: {
      detail: {
        type: 'string',
      },
      publisher: {
        type: 'string',
      },
      source_page_url: {
        type: 'string',
      },
    },
    required: ['source_page_url', 'publisher', 'detail'],
    type: 'object',
  },
  MonitoringReadinessResponse: {
    properties: {
      detail: {
        type: 'string',
      },
      durable_storage: {
        type: 'boolean',
      },
      projection_available: {
        type: 'boolean',
      },
      scheduler_worker_configured: {
        type: 'boolean',
      },
      status: {
        enum: ['ready', 'degraded', 'unavailable'],
        type: 'string',
      },
    },
    required: [
      'status',
      'durable_storage',
      'scheduler_worker_configured',
      'projection_available',
      'detail',
    ],
    type: 'object',
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
  MultiPolygon: {
    properties: {
      polygons: {
        items: {
          $ref: '#/components/schemas/Polygon',
        },
        type: 'array',
      },
    },
    required: ['polygons'],
    type: 'object',
  },
  OpenPanelOperatorActionResponse: {
    additionalProperties: false,
    properties: {
      action_id: {
        type: 'string',
      },
      action_type: {
        const: 'open_panel',
        type: 'string',
      },
      label: {
        maxLength: 160,
        minLength: 1,
        type: 'string',
      },
      operation: {
        const: 'open',
        type: 'string',
      },
      risk: {
        const: 'automatic',
        type: 'string',
      },
      target: {
        const: 'panel',
        type: 'string',
      },
      value: {
        enum: ['findings', 'sources', 'watches', 'operations'],
        type: 'string',
      },
    },
    required: [
      'action_id',
      'action_type',
      'risk',
      'operation',
      'target',
      'value',
      'label',
    ],
    type: 'object',
  },
  OperationalPresence: {
    properties: {
      acronym: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      admin1_code: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      admin1_name: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      country_code: {
        type: 'string',
      },
      dataset_id: {
        type: 'string',
      },
      dataset_updated_at: {
        format: 'date-time',
        type: 'string',
      },
      license_name: {
        type: 'string',
      },
      organization: {
        type: 'string',
      },
      presence_id: {
        type: 'string',
      },
      retrieved_at: {
        format: 'date-time',
        type: 'string',
      },
      sector: {
        type: 'string',
      },
      source_id: {
        type: 'string',
      },
      source_url: {
        type: 'string',
      },
    },
    required: [
      'presence_id',
      'source_id',
      'organization',
      'acronym',
      'sector',
      'country_code',
      'admin1_code',
      'admin1_name',
      'dataset_id',
      'dataset_updated_at',
      'retrieved_at',
      'source_url',
      'license_name',
    ],
    type: 'object',
  },
  OperatorActionScopeResponse: {
    additionalProperties: false,
    properties: {
      country_code: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      country_name: {
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
        enum: ['country', 'worldwide'],
        type: 'string',
      },
    },
    required: ['kind'],
    type: 'object',
  },
  OsmCompletenessIndicator: {
    properties: {
      calculated_at: {
        format: 'date-time',
        type: 'string',
      },
      critical_facility_density_per_sq_km: {
        anyOf: [
          {
            type: 'number',
          },
          {
            type: 'null',
          },
        ],
      },
      dataset_id: {
        type: 'string',
      },
      dataset_version: {
        type: 'string',
      },
      limitation: {
        type: 'string',
      },
      mapped_feature_count: {
        type: 'integer',
      },
      named_feature_fraction: {
        anyOf: [
          {
            type: 'number',
          },
          {
            type: 'null',
          },
        ],
      },
      quality: {
        anyOf: [
          {
            $ref: '#/components/schemas/OsmCompletenessQuality',
          },
          {
            type: 'string',
          },
        ],
      },
      road_density_km_per_sq_km: {
        anyOf: [
          {
            type: 'number',
          },
          {
            type: 'null',
          },
        ],
      },
      source_updated_at: {
        format: 'date-time',
        type: 'string',
      },
    },
    required: [
      'dataset_id',
      'dataset_version',
      'source_updated_at',
      'calculated_at',
      'mapped_feature_count',
      'named_feature_fraction',
      'road_density_km_per_sq_km',
      'critical_facility_density_per_sq_km',
      'quality',
      'limitation',
    ],
    type: 'object',
  },
  OsmCompletenessQuality: {
    enum: ['good', 'limited', 'poor', 'unknown'],
    type: 'string',
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
  Polygon: {
    properties: {
      exterior: {
        $ref: '#/components/schemas/LinearRing',
      },
      holes: {
        items: {
          $ref: '#/components/schemas/LinearRing',
        },
        type: 'array',
      },
    },
    required: ['exterior'],
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
  PopulationDisagreement: {
    properties: {
      absolute_difference: {
        type: 'number',
      },
      comparison_dataset_id: {
        type: 'string',
      },
      primary_dataset_id: {
        type: 'string',
      },
      relative_difference: {
        anyOf: [
          {
            type: 'number',
          },
          {
            type: 'null',
          },
        ],
      },
    },
    required: [
      'primary_dataset_id',
      'comparison_dataset_id',
      'absolute_difference',
      'relative_difference',
    ],
    type: 'object',
  },
  PopulationExposureEstimate: {
    properties: {
      calculated_at: {
        format: 'date-time',
        type: 'string',
      },
      dataset: {
        $ref: '#/components/schemas/ExposureDataset',
      },
      estimate_id: {
        type: 'string',
      },
      geometry_hash: {
        type: 'string',
      },
      lineage: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
      lower_bound: {
        anyOf: [
          {
            type: 'number',
          },
          {
            type: 'null',
          },
        ],
      },
      population: {
        type: 'number',
      },
      upper_bound: {
        anyOf: [
          {
            type: 'number',
          },
          {
            type: 'null',
          },
        ],
      },
    },
    required: [
      'estimate_id',
      'population',
      'dataset',
      'geometry_hash',
      'calculated_at',
      'lineage',
    ],
    type: 'object',
  },
  ProviderTier: {
    enum: ['primary', 'secondary'],
    type: 'string',
  },
  ReportedFact: {
    properties: {
      category: {
        type: 'string',
      },
      claim_id: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      event_id: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      label: {
        type: 'string',
      },
      observed_at: {
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
      reported_location: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      source: {
        $ref: '#/components/schemas/SourceReference',
      },
      status: {
        $ref: '#/components/schemas/FactStatus',
      },
      value: {
        type: 'string',
      },
    },
    required: ['category', 'label', 'value', 'status', 'source'],
    type: 'object',
  },
  ReportedImpact: {
    properties: {
      excerpt: {
        type: 'string',
      },
      fact: {
        $ref: '#/components/schemas/ReportedFact',
      },
      qualifiers: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
    },
    required: ['fact', 'excerpt'],
    type: 'object',
  },
  ReportedImpactResponse: {
    properties: {
      category: {
        enum: [
          'fatalities',
          'injuries',
          'displacement',
          'roads_bridges',
          'electricity',
          'water',
          'communications',
        ],
        type: 'string',
      },
      excerpt: {
        type: 'string',
      },
      label: {
        type: 'string',
      },
      qualifiers: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
      value: {
        type: 'string',
      },
    },
    required: ['category', 'label', 'value', 'excerpt'],
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
  SatelliteAvailabilityResponse: {
    properties: {
      products: {
        items: {
          $ref: '#/components/schemas/SatelliteProductAvailability',
        },
        type: 'array',
      },
    },
    required: ['products'],
    type: 'object',
  },
  SatelliteProductAvailability: {
    properties: {
      default_time: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      limitations: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
      metadata_retrieved_at: {
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
      source_id: {
        type: 'string',
      },
      state: {
        enum: ['available', 'empty', 'degraded', 'error'],
        type: 'string',
      },
      time_values: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
    },
    required: [
      'source_id',
      'state',
      'default_time',
      'time_values',
      'metadata_retrieved_at',
    ],
    type: 'object',
  },
  SectionEvidenceResponse: {
    properties: {
      contract_version: {
        type: 'string',
      },
      evidence: {
        $ref: '#/components/schemas/StandaloneEvidenceResult',
      },
    },
    required: ['evidence'],
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
      lineage_ids: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
      location: {
        type: 'string',
      },
      location_source: {
        anyOf: [
          {
            $ref: '#/components/schemas/SourceResponse',
          },
          {
            type: 'null',
          },
        ],
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
      supplemental_geometry: {
        items: {
          $ref: '#/components/schemas/CycloneMapLayerResponse',
        },
        type: 'array',
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
  Sensor: {
    enum: ['sentinel-1', 'sentinel-2'],
    type: 'string',
  },
  SetTimeWindowOperatorActionResponse: {
    additionalProperties: false,
    properties: {
      action_id: {
        type: 'string',
      },
      action_type: {
        const: 'set_time_window',
        type: 'string',
      },
      label: {
        maxLength: 160,
        minLength: 1,
        type: 'string',
      },
      operation: {
        const: 'set',
        type: 'string',
      },
      risk: {
        const: 'automatic',
        type: 'string',
      },
      target: {
        const: 'time_window',
        type: 'string',
      },
      value: {
        enum: ['1h', '6h', '24h', '48h', '7d'],
        type: 'string',
      },
    },
    required: [
      'action_id',
      'action_type',
      'risk',
      'operation',
      'target',
      'value',
      'label',
    ],
    type: 'object',
  },
  ShowLayerOperatorActionResponse: {
    additionalProperties: false,
    properties: {
      action_id: {
        type: 'string',
      },
      action_type: {
        const: 'show_layer',
        type: 'string',
      },
      label: {
        maxLength: 160,
        minLength: 1,
        type: 'string',
      },
      operation: {
        const: 'show',
        type: 'string',
      },
      risk: {
        const: 'automatic',
        type: 'string',
      },
      target: {
        const: 'map_layer',
        type: 'string',
      },
      value: {
        enum: [
          'active-incidents',
          'satellite-imagery',
          'cop-evidence',
          'cyclone-supplemental',
          'authoritative-weather-alerts',
          'compound-correlations',
        ],
        type: 'string',
      },
    },
    required: [
      'action_id',
      'action_type',
      'risk',
      'operation',
      'target',
      'value',
      'label',
    ],
    type: 'object',
  },
  SourceAuthority: {
    enum: [
      'national_authority',
      'scientific_authority',
      'humanitarian_aggregator',
      'secondary',
    ],
    type: 'string',
  },
  SourceCatalogItemResponse: {
    properties: {
      access_model: {
        anyOf: [
          {
            enum: ['public', 'free_account', 'self_hosted', 'paid'],
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      attribution: {
        type: 'string',
      },
      authority: {
        type: 'string',
      },
      country_codes: {
        anyOf: [
          {
            items: {
              type: 'string',
            },
            type: 'array',
          },
          {
            type: 'null',
          },
        ],
      },
      coverage_description: {
        type: 'string',
      },
      documentation_path: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      freshness_semantics: {
        type: 'string',
      },
      geographic_scopes: {
        items: {
          enum: ['country', 'worldwide'],
          type: 'string',
        },
        type: 'array',
      },
      information_roles: {
        items: {
          type: 'string',
        },
        type: 'array',
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
      limitations: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
      operational_state: {
        $ref: '#/components/schemas/SourceOperationalStateResponse',
      },
      provider: {
        type: 'string',
      },
      publisher: {
        type: 'string',
      },
      rights_id: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      rights_reviewed_at: {
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
      stale_threshold_seconds: {
        anyOf: [
          {
            type: 'integer',
          },
          {
            type: 'null',
          },
        ],
      },
      supported_disasters: {
        items: {
          $ref: '#/components/schemas/Disaster',
        },
        type: 'array',
      },
    },
    required: [
      'source_id',
      'provider',
      'publisher',
      'authority',
      'coverage_description',
      'freshness_semantics',
      'attribution',
      'operational_state',
    ],
    type: 'object',
  },
  SourceCatalogResponse: {
    properties: {
      catalog_version: {
        type: 'string',
      },
      sources: {
        items: {
          $ref: '#/components/schemas/SourceCatalogItemResponse',
        },
        type: 'array',
      },
    },
    required: ['catalog_version'],
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
  SourceOperationalStateResponse: {
    properties: {
      availability: {
        enum: ['available', 'unconfigured', 'maintained_only'],
        type: 'string',
      },
      availability_detail: {
        type: 'string',
      },
      configured: {
        type: 'boolean',
      },
      execution_roles: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
      provider_tier: {
        anyOf: [
          {
            enum: ['primary', 'secondary'],
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      registered: {
        type: 'boolean',
      },
    },
    required: ['registered', 'configured', 'availability', 'availability_detail'],
    type: 'object',
  },
  SourceReference: {
    properties: {
      authority: {
        $ref: '#/components/schemas/SourceAuthority',
      },
      canonical_url: {
        type: 'string',
      },
      publication_precision: {
        enum: ['exact', 'day', 'unknown'],
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
    required: [
      'source_id',
      'publisher',
      'title',
      'canonical_url',
      'published_at',
      'updated_at',
      'retrieved_at',
    ],
    type: 'object',
  },
  SourceResponse: {
    properties: {
      authority: {
        $ref: '#/components/schemas/SourceAuthority',
      },
      canonical_url: {
        type: 'string',
      },
      publication_precision: {
        enum: ['exact', 'day', 'unknown'],
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
      source_age_seconds: {
        anyOf: [
          {
            type: 'number',
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
  StandaloneEvidenceResult: {
    properties: {
      baseline: {
        anyOf: [
          {
            $ref: '#/components/schemas/BaselineVulnerabilityContext',
          },
          {
            type: 'null',
          },
        ],
      },
      event_id: {
        type: 'string',
      },
      exposure: {
        anyOf: [
          {
            $ref: '#/components/schemas/ExposureAnalysis',
          },
          {
            type: 'null',
          },
        ],
      },
      facts: {
        items: {
          $ref: '#/components/schemas/ReportedFact',
        },
        type: 'array',
      },
      forecast_layers: {
        items: {
          $ref: '#/components/schemas/CycloneMapLayer',
        },
        type: 'array',
      },
      humanitarian: {
        anyOf: [
          {
            $ref: '#/components/schemas/HumanitarianContextSnapshot',
          },
          {
            type: 'null',
          },
        ],
      },
      limitations: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
      media: {
        anyOf: [
          {
            $ref: '#/components/schemas/DisasterMediaGallery',
          },
          {
            type: 'null',
          },
        ],
      },
      narratives: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
      physical_event_id: {
        type: 'string',
      },
      reason_codes: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
      reported_accounts: {
        items: {
          $ref: '#/components/schemas/ReportedImpact',
        },
        type: 'array',
      },
      retrieved_at: {
        format: 'date-time',
        type: 'string',
      },
      section: {
        enum: ['impacts', 'warnings', 'forecast', 'exposure', 'humanitarian', 'media'],
        type: 'string',
      },
      state: {
        enum: ['available', 'empty', 'unconfigured', 'degraded', 'error'],
        type: 'string',
      },
      warnings: {
        items: {
          $ref: '#/components/schemas/AssociatedWarning',
        },
        type: 'array',
      },
    },
    required: ['event_id', 'physical_event_id', 'section', 'state', 'retrieved_at'],
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
  WarningAssociation: {
    properties: {
      basis: {
        $ref: '#/components/schemas/WarningAssociationBasis',
      },
      confirmed: {
        type: 'boolean',
      },
      event_id: {
        type: 'string',
      },
      rationale: {
        type: 'string',
      },
      warning_identifier: {
        type: 'string',
      },
    },
    required: ['warning_identifier', 'event_id', 'basis', 'confirmed', 'rationale'],
    type: 'object',
  },
  WarningAssociationBasis: {
    enum: ['explicit_incident_id', 'time_and_geometry'],
    type: 'string',
  },
  WarningCertainty: {
    enum: ['observed', 'likely', 'possible', 'unlikely', 'unknown'],
    type: 'string',
  },
  WarningSeverity: {
    enum: ['extreme', 'severe', 'moderate', 'minor', 'unknown'],
    type: 'string',
  },
  WarningUrgency: {
    enum: ['immediate', 'expected', 'future', 'past', 'unknown'],
    type: 'string',
  },
  WeatherAlertCoordinateResponse: {
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
  WeatherAlertCoverageResponse: {
    properties: {
      detail: {
        type: 'string',
      },
      geographic_scope: {
        type: 'string',
      },
      limitations: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
      publisher: {
        type: 'string',
      },
      source_id: {
        type: 'string',
      },
      state: {
        enum: ['alerts_found', 'no_active_alerts', 'degraded', 'unavailable'],
        type: 'string',
      },
    },
    required: ['source_id', 'publisher', 'state', 'detail', 'geographic_scope'],
    type: 'object',
  },
  WeatherAlertGeometryResponse: {
    properties: {
      kind: {
        const: 'polygon',
        type: 'string',
      },
      rings: {
        items: {
          items: {
            $ref: '#/components/schemas/WeatherAlertCoordinateResponse',
          },
          type: 'array',
        },
        type: 'array',
      },
    },
    type: 'object',
  },
  WeatherAlertResponse: {
    properties: {
      affected_area: {
        type: 'string',
      },
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
      certainty: {
        enum: ['observed', 'likely', 'possible', 'unlikely', 'unknown'],
        type: 'string',
      },
      effective: {
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
      event: {
        type: 'string',
      },
      event_codes: {
        items: {
          items: {
            type: 'string',
          },
          type: 'array',
        },
        type: 'array',
      },
      expires: {
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
      geometry: {
        anyOf: [
          {
            $ref: '#/components/schemas/WeatherAlertGeometryResponse',
          },
          {
            type: 'null',
          },
        ],
      },
      headline: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      languages: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
      lifecycle_state: {
        enum: ['active', 'expired', 'cancelled'],
        type: 'string',
      },
      limitations: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
      message_type: {
        type: 'string',
      },
      onset: {
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
      profile: {
        anyOf: [
          {
            type: 'string',
          },
          {
            type: 'null',
          },
        ],
      },
      provider_alert_id: {
        type: 'string',
      },
      publisher: {
        type: 'string',
      },
      retrieved_at: {
        format: 'date-time',
        type: 'string',
      },
      scope: {
        type: 'string',
      },
      sender: {
        type: 'string',
      },
      sent: {
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
      severity: {
        enum: ['extreme', 'severe', 'moderate', 'minor', 'unknown'],
        type: 'string',
      },
      signature_present: {
        type: 'boolean',
      },
      signature_verified: {
        anyOf: [
          {
            type: 'boolean',
          },
          {
            type: 'null',
          },
        ],
      },
      source_id: {
        type: 'string',
      },
      status: {
        type: 'string',
      },
      superseded_identifiers: {
        items: {
          type: 'string',
        },
        type: 'array',
      },
      urgency: {
        enum: ['immediate', 'expected', 'future', 'past', 'unknown'],
        type: 'string',
      },
    },
    required: [
      'provider_alert_id',
      'source_id',
      'publisher',
      'sender',
      'event',
      'severity',
      'urgency',
      'certainty',
      'affected_area',
      'retrieved_at',
      'attribution',
      'status',
      'message_type',
      'scope',
      'lifecycle_state',
    ],
    type: 'object',
  },
  WeatherAlertsSnapshotResponse: {
    properties: {
      alerts: {
        items: {
          $ref: '#/components/schemas/WeatherAlertResponse',
        },
        type: 'array',
      },
      coverage: {
        $ref: '#/components/schemas/WeatherAlertCoverageResponse',
      },
      retrieved_at: {
        format: 'date-time',
        type: 'string',
      },
      warnings: {
        items: {
          $ref: '#/components/schemas/WeatherAlertWarningResponse',
        },
        type: 'array',
      },
    },
    required: ['retrieved_at', 'coverage'],
    type: 'object',
  },
  WeatherAlertWarningResponse: {
    properties: {
      detail: {
        type: 'string',
      },
      partial: {
        type: 'boolean',
      },
      reason_code: {
        type: 'string',
      },
      retryable: {
        type: 'boolean',
      },
    },
    required: ['reason_code', 'detail', 'retryable', 'partial'],
    type: 'object',
  },
} as const;

export type ApiSchemaName = keyof typeof apiSchemas;

export function matchesApiSchema(name: ApiSchemaName, value: unknown): boolean {
  return matchesOpenApiSchema(value, apiSchemas[name], apiSchemas);
}

export type AcquisitionAudit = {
  article_attempts?: number;
  article_failures?: number;
  budget_excluded?: number;
  duplicate_urls?: number;
  invalid_leads?: number;
  leads_received?: number;
  partition: string;
  provider: string;
};

export type ActiveIncidentCountryResponse = {
  association_basis:
    'coordinate_polygon' | 'source_mention' | 'named_region' | 'nearby_boundary';
  code: string;
  distance_km?: number | null;
  name: string;
};

export type ActiveIncidentResponse = {
  activity_status?: IncidentActivityStatus;
  association_reasons?: Array<string>;
  collection_notices?: Array<string>;
  country?: ActiveIncidentCountryResponse | null;
  detection?: IncidentDetectionTimelineResponse;
  disaster: Disaster;
  discovery_reports?: Array<DiscoveryReportResponse>;
  event_id: string;
  event_time: string | null;
  event_time_basis?: 'reported' | 'unknown';
  event_time_end?: string | null;
  event_time_precision?: EventTimePrecision;
  evidence_sources?: Array<SourceResponse>;
  geometry?: EventGeometryResponse | null;
  identity_status?: 'candidate' | 'associated' | null;
  independent_origins?: number | null;
  last_meaningful_change_at?: string | null;
  lineage_ids?: Array<string>;
  location: string;
  measurements?: Array<EventMeasurementResponse>;
  observation_kind?: 'physical_event' | 'preliminary_event' | 'acquisition';
  physical_event_id?: string | null;
  provider_ids?: Array<string>;
  provider_tier: ProviderTier;
  source: SourceResponse;
  source_authority: SourceAuthority;
  verification_status?: 'provisional_news_detected' | 'source_backed' | 'rejected';
};

export type ActiveIncidentsSnapshotResponse = {
  correlations?: Array<CompoundHazardCorrelationResponse>;
  coverage?: Array<DisasterIncidentCoverageResponse>;
  has_more?: boolean;
  historical_limitations?: Array<string>;
  incidents?: Array<ActiveIncidentResponse>;
  is_stale?: boolean;
  next_cursor?: string | null;
  observations?: Array<ActiveIncidentResponse>;
  refresh_state?: 'fresh' | 'refreshing' | 'stale';
  retrieved_at: string;
  snapshot_version?: string | null;
  total_incident_count?: number | null;
  warnings?: Array<string>;
};

export type AnalystNoteRequest = {
  incident_id?: string | null;
  tags?: Array<string>;
  text: string;
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
  claims?: Array<EvidenceClaimResponse>;
  common_operational_picture?: CommonOperationalPictureResponse | null;
  conversation_id: string;
  decision_support?: DecisionSupportResponse | null;
  investigation?: InvestigationResponse | null;
  investigation_case?: InvestigationCaseResponse | null;
  map_action?: MapNavigationActionResponse | null;
  media_gallery?: DisasterMediaGalleryResponse | null;
  message: string;
  model: string;
  multimodal?: MultimodalStateResponse | null;
  operator_actions?: Array<
    | OpenPanelOperatorActionResponse
    | SetTimeWindowOperatorActionResponse
    | ShowLayerOperatorActionResponse
    | CreateIncidentWatchOperatorActionResponse
  >;
  original_message?: string | null;
  partial?: boolean;
  response_language?: string | null;
  response_type?: string;
  retrieval_time?: string | null;
  sections?: Array<ReportSectionResponse>;
  selected_event?: SelectedEventResponse | null;
  sources?: Array<SourceResponse>;
  timeline?: Array<EvidenceTimelineEntryResponse>;
  warnings?: Array<string>;
};

export type AssociatedWarning = {
  alert: CapAlert;
  association: WarningAssociation;
};

export type BaselineVulnerabilityContext = {
  aggregation_level: string;
  context_role: string;
  coping_capacity_index: number;
  dataset_version: string;
  interpretation: string;
  place_code: string;
  place_name: string;
  risk_index: number;
  source_id: string;
  vintage: number;
  vulnerability_index: number;
};

export type BookmarkRequest = {
  incident_id?: string | null;
  label: string;
  target_id: string;
  target_type: string;
};

export type CapAlert = {
  addresses?: Array<string>;
  attribution: string;
  canonical_url?: string | null;
  codes?: Array<string>;
  identifier: string;
  incidents?: Array<string>;
  infos: Array<CapInfo>;
  limitations: Array<string>;
  message_type: CapMessageType;
  note?: string | null;
  profile?: string | null;
  publisher: string;
  references?: Array<CapMessageReference>;
  restriction?: string | null;
  retrieved_at: string;
  scope: CapScope;
  sender: string;
  sent: string;
  signature_present?: boolean;
  signature_verified?: boolean | null;
  source?: string | null;
  source_id: string;
  status: CapStatus;
};

export type CapArea = {
  altitude_m?: number | null;
  ceiling_m?: number | null;
  circles?: Array<CapCircle>;
  description: string;
  geocodes?: Array<[string, string]>;
  polygons?: Array<MultiPolygon>;
};

export type CapCircle = {
  center: Coordinate;
  radius_km: number;
};

export type CapInfo = {
  areas: Array<CapArea>;
  categories: Array<string>;
  certainty: WarningCertainty;
  description: string | null;
  effective: string | null;
  event: string;
  event_codes: Array<[string, string]>;
  expires: string | null;
  headline: string | null;
  instruction: string | null;
  language: string;
  onset: string | null;
  parameters?: Array<[string, string]>;
  sender_name: string | null;
  severity: WarningSeverity;
  urgency: WarningUrgency;
};

export type CapMessageReference = {
  identifier: string;
  sender: string;
  sent: string;
};

export type CapMessageType = 'alert' | 'update' | 'cancel' | 'ack' | 'error';

export type CapScope = 'public' | 'restricted' | 'private';

export type CapStatus = 'actual' | 'exercise' | 'system' | 'test' | 'draft';

export type CaptureRole = 'pre_event' | 'post_event' | 'single_capture' | 'unknown';

export type CaseNotebookRequest = {
  created_by: string;
  incident_ids?: Array<string>;
  title: string;
};

export type CommonOperationalPictureResponse = {
  cop_id: string;
  created_at: string;
  layers: Array<SourceMapLayerResponse | AnalyticalMapLayerResponse>;
  multimodal_state_version: string;
  physical_event_id: string;
  status: string;
  updated_at: string;
};

export type CompoundHazardCorrelationResponse = {
  correlation_id: string;
  distance_km: number;
  first_disaster: Disaster;
  first_event_id: string;
  first_physical_event_id?: string | null;
  limitation: string;
  relationship: 'spatiotemporal_association';
  rule_id: string;
  second_disaster: Disaster;
  second_event_id: string;
  second_physical_event_id?: string | null;
  source_ids?: Array<string>;
  summary: string;
  time_delta_seconds: number;
};

export type ContextAvailability = 'available' | 'partial' | 'no_data' | 'unavailable';

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

export type Coordinate = {
  latitude: number;
  longitude: number;
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

export type CountryIncidentWatchScopeRequest = {
  country: string;
  kind: 'country';
};

export type CreateIncidentWatchOperatorActionResponse = {
  action_id: string;
  action_type: 'create_incident_watch';
  disaster: Disaster;
  label: string;
  refresh_interval_seconds: 900 | 1800 | 3600 | 21600 | 86400;
  risk: 'confirmation_required';
  scope: OperatorActionScopeResponse;
};

export type CrossHazardAssessmentResponse = {
  limitation: string;
  status:
    'associated' | 'not_established' | 'unsupported_pair' | 'insufficient_evidence';
  summary: string;
};

export type CycloneMapCoordinate = {
  latitude: number;
  longitude: number;
  valid_at?: string | null;
};

export type CycloneMapCoordinateResponse = {
  latitude: number;
  longitude: number;
  valid_at?: string | null;
};

export type CycloneMapGeometryKind = 'point' | 'track' | 'area';

export type CycloneMapLayer = {
  coordinates: Array<CycloneMapCoordinate>;
  geometry_kind: CycloneMapGeometryKind;
  issued_at: string;
  layer_id: string;
  limitation: string;
  provisional: boolean;
  reconciliation: string;
  semantic_role: CycloneMapSemanticRole;
  source: SourceReference;
  storm_id: string;
  valid_from: string | null;
  valid_to: string | null;
  wind_threshold?: number | null;
  wind_threshold_unit?: string | null;
};

export type CycloneMapLayerResponse = {
  coordinates: Array<CycloneMapCoordinateResponse>;
  geometry_kind: 'point' | 'track' | 'area';
  issued_at: string;
  layer_id: string;
  limitation: string;
  provisional: boolean;
  reconciliation: string;
  semantic_role:
    'provisional_track' | 'forecast_track' | 'uncertainty_area' | 'wind_radii';
  source: SourceResponse;
  storm_id: string;
  valid_from?: string | null;
  valid_to?: string | null;
  wind_threshold?: number | null;
  wind_threshold_unit?: string | null;
};

export type CycloneMapSemanticRole =
  'provisional_track' | 'forecast_track' | 'uncertainty_area' | 'wind_radii';

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
  | 'volcanic_eruption'
  | 'drought';

export type DisasterIncidentCoverageResponse = {
  detail: string;
  disaster: Disaster;
  incident_count: number;
  providers?: Array<string>;
  records_seen?: number;
  scan_complete?: boolean;
  state: 'events_found' | 'no_matching_records' | 'degraded' | 'unavailable';
  truncated?: boolean;
};

export type DisasterMediaGallery = {
  candidate_count?: number;
  collection_limit?: number;
  event_id: string;
  generated_at: string;
  items: Array<DisasterMediaItem>;
  physical_event_id: string;
  provider_ids: Array<string>;
  rejected_count: number;
  rejection_reasons?: Array<[string, number]>;
  source_articles?: Array<SourceReference>;
  truncated?: boolean;
  unavailable_sources?: Array<MediaUnavailableSource>;
  warnings?: Array<string>;
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

export type DisasterMediaItem = {
  association_detail: string;
  association_rule_ids: Array<string>;
  association_status: MediaAssociationStatus;
  caption: string;
  captured_at: string | null;
  content_sha256: string;
  credit: string;
  credit_kind: MediaCreditKind;
  event_id: string;
  height: number;
  license_name: string | null;
  license_url: string | null;
  media_id: string;
  physical_event_id: string;
  published_at: string | null;
  publisher: string;
  rights_status: MediaRightsStatus;
  role: MediaContentRole;
  source_id: string;
  source_page_url: string;
  source_references?: Array<MediaSourceAttribution>;
  uncertainty: string;
  width: number;
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
  published_at: string | null;
  publisher: string;
  rights_status: string;
  role: string;
  source_id: string;
  source_page_url: string;
  uncertainty: string;
  width: number;
};

export type DiscoveryReportResponse = {
  access_issue?: string | null;
  claims?: Array<ReportedImpactResponse>;
  event_date_end?: string | null;
  event_date_precision?: 'exact' | 'day' | 'range' | 'unknown';
  event_date_wording?: string | null;
  event_time?: string | null;
  event_year_inferred?: boolean;
  fatality_evidence?: Array<string>;
  geometry?: EventGeometryResponse | null;
  indexed_at?: string | null;
  location?: string | null;
  location_precision?: 'named_place' | 'country_context' | 'unresolved';
  mention_excerpt?: string | null;
  mention_id?: string | null;
  mention_notices?: Array<string>;
  mention_role?: 'reported' | 'ongoing' | 'historical' | 'forecast' | 'uncertain';
  origin?: string | null;
  original_url?: string | null;
  source: SourceResponse;
};

export type DiscoveryScanRequest = {
  reporting_days?: 1 | 3 | 7 | 14 | 30;
};

export type DiscoveryScanResponse = {
  acquisition?: Array<AcquisitionAudit>;
  assessment_counts?: {
    [key: string]: number;
  };
  associated_event_count?: number;
  candidate_count?: number;
  coverage_notice?: string;
  failed_operations: number;
  finished_at: string | null;
  interval_end: string;
  interval_start: string;
  issues: Array<string>;
  reporting_days: number;
  reports_seen: number;
  reprocessed_from?: string | null;
  scan_id: string;
  snapshot: ActiveIncidentsSnapshotResponse;
  status: 'running' | 'completed' | 'incomplete' | 'failed';
  successful_operations: number;
  truncated: boolean;
  uncertain_publication_count?: number;
  unknown_publication_count: number;
  unlocated_count: number;
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

export type EventTimePrecision = 'exact' | 'day' | 'week';

export type EvidenceClaimResponse = {
  alternatives?: Array<EvidenceClaimVariantResponse>;
  claim_id: string;
  claim_key: string;
  contradictions?: Array<EvidenceClaimVariantResponse>;
  disposition: EvidenceDisposition | null;
  gap?: string | null;
  label: string;
  observed_at?: string | null;
  published_at?: string | null;
  retrieved_at?: string | null;
  source: SourceResponse | null;
  status: FactStatus;
  value: string | null;
  why: string;
};

export type EvidenceClaimVariantResponse = {
  disposition: EvidenceDisposition;
  observation_id: string;
  observed_at?: string | null;
  published_at?: string | null;
  retrieved_at: string;
  rule_id: string;
  source: SourceResponse;
  status: FactStatus;
  value: string;
};

export type EvidenceDisposition =
  'current' | 'superseded' | 'conflicting' | 'duplicate' | 'unusable';

export type EvidencePackageCreateRequest = {
  findings?: Array<{
    [key: string]: unknown;
  }>;
  imagery_manifests?: Array<{
    [key: string]: unknown;
  }>;
  incident_id: string;
  incident_snapshot: {
    [key: string]: unknown;
  };
  normalized_data: {
    [key: string]: unknown;
  };
  policy_versions?: Array<string>;
  software_version: string;
  source_links?: Array<string>;
};

export type EvidencePackageVerifyRequest = {
  content_base64: string;
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

export type EvidenceTimelineEntryResponse = {
  claim_key?: string | null;
  detail: string;
  entry_id: string;
  event_type: EvidenceTimelineEventType;
  occurred_at: string;
  published_at?: string | null;
  related_id?: string | null;
  retrieved_at?: string | null;
  source: SourceResponse | null;
  status?: string | null;
  title: string;
};

export type EvidenceTimelineEventType =
  | 'normalized_observation'
  | 'coverage_status'
  | 'warning_lifecycle'
  | 'situation_report'
  | 'imagery_acquisition'
  | 'imagery_selection'
  | 'watch_change'
  | 'claim_reconciliation';

export type ExposureAnalysis = {
  assets: Array<InfrastructureAsset>;
  calculated_at: string;
  display_label: string;
  geometry: ExposureGeometry;
  limitations: Array<string>;
  osm_completeness?: OsmCompletenessIndicator | null;
  population_disagreement: PopulationDisagreement | null;
  population_estimates: Array<PopulationExposureEstimate>;
};

export type ExposureDataset = {
  dataset_id: string;
  license_name: string;
  publisher: string;
  resolution_m: number;
  role: ExposureDatasetRole;
  source_url: string;
  uncertainty: string;
  version: string;
  vintage: number;
};

export type ExposureDatasetRole = 'primary' | 'secondary';

export type ExposureGeometry = {
  geometry: MultiPolygon;
  observed_at: string;
  role: ExposureGeometryRole;
  source_id: string;
  source_version: string;
};

export type ExposureGeometryRole =
  'operator_inspection' | 'mapped_hazard' | 'forecast_hazard' | 'modelled_hazard';

export type ExposureInspectionRequest = {
  bounds: [number, number, number, number];
};

export type ExternalFieldMappingRequest = {
  captured_at: string;
  external_id: string;
  external_verification?: string | null;
  latitude: string;
  longitude: string;
  report_type: string;
  source_created_at: string;
  text: string;
};

export type FactStatus =
  'confirmed' | 'preliminary' | 'estimated' | 'disputed' | 'unknown';

export type FieldAttachmentRequest = {
  content_base64: string;
  filename: string;
  media_type: 'image/jpeg' | 'image/png';
};

export type FieldGeometryRequest = {
  coordinates: Array<unknown>;
  type: 'Point' | 'Polygon';
};

export type FieldReportCreateRequest = {
  attachments?: Array<FieldAttachmentRequest>;
  captured_at: string;
  geometry: FieldGeometryRequest;
  location_precision: LocationPrecision;
  location_uncertainty_m?: number | null;
  report_type: string;
  source_created_at: string;
  submitter_channel: string;
  text: string;
};

export type FieldReportImportRequest = {
  content:
    | string
    | {
        [key: string]: unknown;
      };
  format: 'csv' | 'geojson' | 'ushahidi';
  mapping?: ExternalFieldMappingRequest | null;
  media_packages?: Array<ImportedFieldMediaRequest>;
  source_system: 'kobotoolbox' | 'odk' | 'ushahidi';
};

export type FieldReportReviewDecision =
  'reject' | 'retain_unverified' | 'associate_to_event' | 'admit_operator_observation';

export type FieldReportReviewRequest = {
  authority_policy_id?: string | null;
  decision: FieldReportReviewDecision;
  event_id?: string | null;
  rationale: string;
};

export type FieldReportReviewState =
  | 'pending_review'
  | 'retained_unverified'
  | 'rejected'
  | 'associated'
  | 'admitted_operator_observation';

export type FieldReviewCapabilityResponse = {
  available: boolean;
  reason: 'not_configured' | 'identity_missing' | null;
};

export type FootprintRequest = {
  coordinates: Array<Array<[number, number]>>;
  crs?: 'EPSG:4326';
};

export type GroundImageryArtifactResponse = {
  artifact_id: string;
  byte_count: number;
  content_type: string;
  created_at: string;
  grid: GroundImageryGridResponse;
  observation?: GroundImageryObservationResponse | null;
  output_kind: string;
  role: string;
  selection_id: string;
  sensor: Sensor;
  sha256: string;
  source_product_ids: Array<string>;
  storage_key: string;
};

export type GroundImageryCreateRequest = {
  context_margin_km?: number | null;
  fallback_radius_km?: number | null;
  idempotency_key?: string | null;
  incident_id: string;
  onset_earliest?: string | null;
  onset_latest?: string | null;
  onset_source_id?: string | null;
  owner_scope?: string;
  reference_time?: string | null;
  refresh_if_stale?: boolean;
  region?: {
    [key: string]: unknown;
  } | null;
  sensors?: Array<Sensor>;
};

export type GroundImageryGridResponse = {
  crs: string;
  height: number;
  max_x: number;
  max_y: number;
  min_x: number;
  min_y: number;
  pixel_size_m: number;
  resolution_label: string;
  width: number;
};

export type GroundImageryJobResponse = {
  attempt: number;
  claimed_at?: string | null;
  diagnostic?: string | null;
  error_code?: string | null;
  fencing_token: number;
  job_id: string;
  lease_expires_at?: string | null;
  max_attempts: number;
  next_attempt_at: string;
  request_version: number;
  role: string;
  sensor: Sensor;
  status: string;
};

export type GroundImageryManifestResponse = {
  artifacts?: Array<{
    [key: string]: unknown;
  }>;
  disaster: string;
  incident_id: string;
  manifest_version: string;
  observations: Array<{
    [key: string]: unknown;
  }>;
  onset: {
    [key: string]: unknown;
  } | null;
  reason_codes: Array<string>;
  reference_time: string;
  region: {
    [key: string]: unknown;
  } | null;
  request_id: string;
  request_version: number;
  selections: Array<{
    [key: string]: unknown;
  }>;
  state: string;
  temporal_policy_version: string;
};

export type GroundImageryObservationPageResponse = {
  next_cursor: string | null;
  observations: Array<GroundImageryObservationResponse>;
  total: number;
};

export type GroundImageryObservationResponse = {
  acquisition_id: string | null;
  captured_end: string;
  captured_start: string;
  cloud_cover_fraction: number | null;
  footprint: {
    [key: string]: unknown;
  };
  mode: string | null;
  observation_id: string;
  orbit_direction: string | null;
  platform: string | null;
  polarizations: Array<string>;
  product_id: string;
  quality: GroundImageryQualityResponse | null;
  readiness: string;
  relative_orbit: number | null;
  revision: string | null;
  sensor: Sensor;
  source_url: string | null;
};

export type GroundImageryPrepareRequest = {
  output_kind?: string | null;
  overview?: boolean;
  role: string;
  sensor: Sensor;
};

export type GroundImageryQualityResponse = {
  component_usable_fractions: {
    [key: string]: number;
  };
  covered_fraction: number;
  mask_definition: string;
  obscured_fraction: number;
  quality_state: string;
  uncertain_fraction: number;
  uncovered_fraction: number;
  usable_fraction: number;
};

export type GroundImageryReadinessResponse = {
  detail: string;
  state: string;
};

export type GroundImageryRegionRequest = {
  context_margin_km?: number | null;
  region: {
    [key: string]: unknown;
  };
};

export type GroundImageryRegionResolutionResponse = {
  alternatives?: Array<{
    [key: string]: unknown;
  }>;
  reason_code?: string | null;
  region: GroundImageryRegionResponse | null;
  state: 'resolved' | 'ambiguous' | 'needs_region';
  warnings?: Array<string>;
};

export type GroundImageryRegionResponse = {
  association: string;
  core: {
    [key: string]: unknown;
  };
  geometry_hash: string;
  inspection: {
    [key: string]: unknown;
  };
  region_id: string;
  source_footprints: Array<{
    [key: string]: unknown;
  }>;
  version: number;
};

export type GroundImageryRequestResponse = {
  artifacts?: Array<GroundImageryArtifactResponse>;
  disaster: string;
  incident_id: string;
  jobs?: Array<GroundImageryJobResponse>;
  next_check_at?: string | null;
  reason_codes: Array<string>;
  reference_time: string;
  region: GroundImageryRegionResolutionResponse;
  request_id: string;
  request_version: number;
  sensors: Array<GroundImagerySensorStatusResponse>;
  state: string;
  temporal_plan: GroundImageryTemporalPlanResponse;
  watch_enabled?: boolean;
  watch_interval_seconds?: number | null;
};

export type GroundImagerySelectionRequest = {
  observation_id: string;
  role: string;
  sensor: Sensor;
};

export type GroundImagerySelectionResponse = {
  age_class: string | null;
  alternative_observation_ids: Array<string>;
  explanation: string;
  label: string;
  observation: GroundImageryObservationResponse | null;
  reason: string;
  role: string;
  selection_id: string;
  sensor: Sensor;
};

export type GroundImagerySensorStatusResponse = {
  failure_code: string | null;
  failure_detail: string | null;
  next_cursor: string | null;
  scan_complete: boolean;
  scanned_count: number;
  selections: Array<GroundImagerySelectionResponse>;
  sensor: Sensor;
};

export type GroundImageryTemporalPlanResponse = {
  impact_start_earliest: string | null;
  impact_start_latest: string | null;
  onset_precision: string | null;
  onset_source_id: string | null;
  policy_version: string;
  reference_time: string;
  windows: Array<GroundImageryTimeWindowResponse>;
};

export type GroundImageryTimeWindowResponse = {
  end: string;
  expanded_end: string;
  expanded_start: string;
  role: string;
  sensor: Sensor;
  start: string;
};

export type GroundImageryWatchRequest = {
  enabled: boolean;
  interval_seconds?: number | null;
};

export type HealthResponse = {
  service: string;
  status: string;
  version: string;
};

export type HTTPValidationError = {
  detail?: Array<ValidationError>;
};

export type HumanitarianContextSnapshot = {
  availability: ContextAvailability;
  country_code: string;
  event_id: string | null;
  gaps: Array<string>;
  indicators: Array<HumanitarianIndicator>;
  limitations: Array<string>;
  operational_presence: Array<OperationalPresence>;
  retrieved_at: string;
};

export type HumanitarianIndicator = {
  admin1_code: string | null;
  admin1_name: string | null;
  causal_attribution?: boolean;
  country_code: string;
  dataset_id: string;
  dataset_updated_at: string;
  dimensions?: Array<[string, string]>;
  indicator_id: string;
  kind: HumanitarianIndicatorKind;
  license_name: string;
  reference_period_end: string;
  reference_period_start: string;
  retrieved_at: string;
  source_id: string;
  source_url: string;
  stale?: boolean;
  unit: string;
  value: number;
};

export type HumanitarianIndicatorKind =
  'baseline_population' | 'displaced_people' | 'food_insecurity';

export type ImportedFieldMediaRequest = {
  content_base64: string;
  external_id: string;
  filename: string;
  media_type: 'image/jpeg' | 'image/png';
};

export type IncidentActivityStatus = 'ongoing' | 'ended' | 'unknown';

export type IncidentDetectionTimelineResponse = {
  assistant_ready_at?: string | null;
  candidate_created_at?: string | null;
  first_observed_at?: string | null;
  monitor_visible_at?: string | null;
  news_break_at?: string | null;
  verified_at?: string | null;
};

export type IncidentView = 'recent' | 'ongoing' | 'recently_updated' | 'historical';

export type IncidentWatchChangeResponse = {
  after_hash: string | null;
  before_hash: string | null;
  change_id: string;
  created_at: string;
  detail: string;
  incident: IncidentWatchEventResponse | null;
  kind:
    | 'new_event'
    | 'observation_gap'
    | 'measurements_changed'
    | 'geometry_changed'
    | 'evidence_set_changed'
    | 'coverage_changed';
  observation_id: string;
  previous_observation_id: string | null;
  read_at: string | null;
  source_ids?: Array<string>;
  summary: string;
  watch_id: string;
};

export type IncidentWatchCreateRequest = {
  disaster: Disaster;
  refresh_interval_seconds: number;
  scope: CountryIncidentWatchScopeRequest | WorldwideIncidentWatchScopeRequest;
};

export type IncidentWatchEnabledRequest = {
  enabled: boolean;
};

export type IncidentWatchEventResponse = {
  disaster: Disaster;
  event_id: string;
  event_time: string;
  evidence_sources?: Array<SourceResponse>;
  geometry: EventGeometryResponse | null;
  location: string;
  measurements?: Array<EventMeasurementResponse>;
  physical_event_id: string;
  provider_ids?: Array<string>;
  provider_tier: ProviderTier;
  source: SourceResponse;
  source_authority: SourceAuthority;
};

export type IncidentWatchMarkReadRequest = {
  change_ids?: Array<string>;
};

export type IncidentWatchMarkReadResponse = {
  marked_read_count: number;
  unread_change_count: number;
  watch_id: string;
};

export type IncidentWatchResponse = {
  coverage_state:
    | 'events_found'
    | 'no_matching_records'
    | 'stale'
    | 'degraded'
    | 'unavailable'
    | null;
  created_at: string;
  disaster: Disaster;
  enabled: boolean;
  last_checked_at: string | null;
  next_refresh_at: string;
  refresh_interval_seconds: number;
  scope: IncidentWatchScopeResponse;
  unread_change_count: number;
  updated_at: string;
  watch_id: string;
};

export type IncidentWatchScopeResponse = {
  country_code: string | null;
  country_name: string | null;
  kind: 'country' | 'worldwide';
};

export type InfrastructureAsset = {
  asset_id: string;
  category: InfrastructureCategory;
  coordinate?: Coordinate | null;
  geometry?: MultiPolygon | null;
  name: string;
  path?: Array<Coordinate>;
  source_dataset_id: string;
  source_version: string;
};

export type InfrastructureCategory =
  | 'hospital'
  | 'clinic'
  | 'school'
  | 'fire_station'
  | 'police'
  | 'bridge'
  | 'major_road'
  | 'power'
  | 'water'
  | 'shelter';

export type InvestigationCaseCountryResponse = {
  country_code: string;
  country_name: string;
};

export type InvestigationCaseResponse = {
  case_id: string;
  correlations?: Array<CompoundHazardCorrelationResponse>;
  countries: Array<InvestigationCaseCountryResponse>;
  country?: InvestigationCaseCountryResponse | null;
  cross_hazard_assessment: CrossHazardAssessmentResponse;
  partial: boolean;
  status: 'completed' | 'partial';
  targets: Array<InvestigationTargetResponse>;
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
  event_issue_codes?: Array<string>;
  event_records_seen?: number;
  event_scan_complete?: boolean | null;
  evidence_count?: number;
  evidence_state_version?: string | null;
  geographic_scope?: string;
  information_needs?: Array<string>;
  output_modalities?: Array<string>;
  physical_event_count?: number;
  physical_event_id?: string | null;
  place_candidate_count?: number;
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

export type InvestigationTargetResponse = {
  country_code: string;
  country_name: string;
  disaster: Disaster;
  partial: boolean;
  sections?: Array<ReportSectionResponse>;
  selected_event?: SelectedEventResponse | null;
  sources?: Array<SourceResponse>;
  status: 'completed' | 'partial' | 'coverage_unavailable' | 'failed';
  target_id: string;
  termination_reason: string;
  warnings?: Array<string>;
};

export type LinearRing = {
  coordinates: Array<Coordinate>;
};

export type LineStringGeometryResponse = {
  coordinates: Array<[number, number]>;
  crs: 'EPSG:4326';
  type: 'LineString';
};

export type LocationPrecision = 'exact' | 'approximate' | 'unknown';

export type MapNavigationActionResponse = {
  bounds: [number, number, number, number];
  label: string;
  max_zoom?: number;
  type?: 'fit_bounds';
};

export type MappingWorkflowRequest = {
  aoi: {
    [key: string]: unknown;
  };
  incident_id: string;
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
  | 'maximum_wind_speed'
  | 'provider_significance'
  | 'confidence'
  | 'fire_radiative_power'
  | 'burned_area'
  | 'severity';

export type MediaAssociationStatus = 'exact_event_link' | 'corroborated' | 'rejected';

export type MediaContentRole =
  | 'aftermath'
  | 'rescue_effort'
  | 'relief_operation'
  | 'scientific_overview'
  | 'relevant_scene';

export type MediaCreditKind = 'photographer' | 'agency' | 'publisher';

export type MediaRightsStatus = 'licensed_reuse' | 'source_preview';

export type MediaSourceAttribution = {
  caption: string;
  captured_at: string | null;
  credit: string;
  credit_kind: MediaCreditKind;
  published_at: string | null;
  publisher: string;
  rights_status: MediaRightsStatus;
  source_page_url: string;
};

export type MediaUnavailableSource = {
  detail: string;
  publisher: string;
  source_page_url: string;
};

export type MonitoringReadinessResponse = {
  detail: string;
  durable_storage: boolean;
  projection_available: boolean;
  scheduler_worker_configured: boolean;
  status: 'ready' | 'degraded' | 'unavailable';
};

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

export type MultiPolygon = {
  polygons: Array<Polygon>;
};

export type NotebookEntryRequest = {
  content: string;
  created_by: string;
  kind: string;
  reference_id?: string | null;
  title: string;
};

export type OpenPanelOperatorActionResponse = {
  action_id: string;
  action_type: 'open_panel';
  label: string;
  operation: 'open';
  risk: 'automatic';
  target: 'panel';
  value: 'findings' | 'sources' | 'watches' | 'operations';
};

export type OperationalPresence = {
  acronym: string | null;
  admin1_code: string | null;
  admin1_name: string | null;
  country_code: string;
  dataset_id: string;
  dataset_updated_at: string;
  license_name: string;
  organization: string;
  presence_id: string;
  retrieved_at: string;
  sector: string;
  source_id: string;
  source_url: string;
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

export type OperatorActionScopeResponse = {
  country_code?: string | null;
  country_name?: string | null;
  kind: 'country' | 'worldwide';
};

export type OperatorDecision = 'reviewed' | 'approved_bounded' | 'rejected';

export type OsmCompletenessIndicator = {
  calculated_at: string;
  critical_facility_density_per_sq_km: number | null;
  dataset_id: string;
  dataset_version: string;
  limitation: string;
  mapped_feature_count: number;
  named_feature_fraction: number | null;
  quality: OsmCompletenessQuality | string;
  road_density_km_per_sq_km: number | null;
  source_updated_at: string;
};

export type OsmCompletenessQuality = 'good' | 'limited' | 'poor' | 'unknown';

export type PointGeometryResponse = {
  coordinates: [number, number];
  crs: 'EPSG:4326';
  type: 'Point';
};

export type Polygon = {
  exterior: LinearRing;
  holes?: Array<LinearRing>;
};

export type PolygonGeometryResponse = {
  coordinates: Array<Array<[number, number]>>;
  crs: 'EPSG:4326';
  type: 'Polygon';
};

export type PopulationDisagreement = {
  absolute_difference: number;
  comparison_dataset_id: string;
  primary_dataset_id: string;
  relative_difference: number | null;
};

export type PopulationExposureEstimate = {
  calculated_at: string;
  dataset: ExposureDataset;
  estimate_id: string;
  geometry_hash: string;
  lineage: Array<string>;
  lower_bound?: number | null;
  population: number;
  upper_bound?: number | null;
};

export type ProviderBudgetResponse = {
  budget_window: string;
  limit_units: number;
  provider_id: string;
  released_units: number;
  remaining_units: number;
  reserved_units: number;
  reset_at: string;
  settled_units: number;
};

export type ProviderFreshnessResponse = {
  admission_failures?: number;
  age_seconds?: number | null;
  consecutive_failures: number;
  effective_at?: string | null;
  expected_freshness_seconds: number;
  hazard?: string | null;
  health_state?: 'healthy' | 'stale' | 'degraded' | 'unavailable' | 'misconfigured';
  last_attempt_at?: string | null;
  last_success_at?: string | null;
  latest_error_code?: string | null;
  parse_failures?: number;
  retrieval_lag_seconds?: number | null;
  source_id: string;
  source_publication_age_seconds?: number | null;
  stale_projection_age_seconds?: number | null;
  state: string;
  truncated?: boolean;
};

export type ProviderTier = 'primary' | 'secondary';

export type ReadinessResponse = {
  model: string;
  model_available: boolean;
  ollama_available: boolean;
  status: string;
};

export type ReportedFact = {
  category: string;
  claim_id?: string | null;
  event_id?: string | null;
  label: string;
  observed_at?: string | null;
  reported_location?: string | null;
  source: SourceReference;
  status: FactStatus;
  value: string;
};

export type ReportedImpact = {
  excerpt: string;
  fact: ReportedFact;
  qualifiers?: Array<string>;
};

export type ReportedImpactResponse = {
  category:
    | 'fatalities'
    | 'injuries'
    | 'displacement'
    | 'roads_bridges'
    | 'electricity'
    | 'water'
    | 'communications';
  excerpt: string;
  label: string;
  qualifiers?: Array<string>;
  value: string;
};

export type ReportSectionResponse = {
  content: string;
  title: string;
};

export type RouteAccessRequest = {
  destination: RouteCoordinateRequest;
  origin: RouteCoordinateRequest;
  profile?: RouteProfile;
};

export type RouteCoordinateRequest = {
  latitude: number;
  longitude: number;
};

export type RouteProfile = 'driving' | 'cycling' | 'walking';

export type RunbookTemplateRequest = {
  name: string;
  steps: Array<string>;
};

export type SatelliteAvailabilityResponse = {
  products: Array<SatelliteProductAvailability>;
};

export type SatelliteImageryCatalogResponse = {
  products: Array<SatelliteImageryProductResponse>;
};

export type SatelliteImageryProductResponse = {
  access_mode: 'direct_gibs' | 'api';
  access_model: 'public' | 'free_account' | 'self_hosted' | 'paid';
  attribution: string;
  available: boolean;
  display_name: string;
  license_name: string;
  maximum_useful_zoom: number;
  provider_id: string;
  provider_name: string;
  rights_id: string;
  source_id: string;
  temporal_mode: 'daily' | 'subdaily' | 'fixed';
  temporal_step_minutes?: number | null;
};

export type SatelliteProductAvailability = {
  default_time: string | null;
  limitations?: Array<string>;
  metadata_retrieved_at: string | null;
  source_id: string;
  state: 'available' | 'empty' | 'degraded' | 'error';
  time_values: Array<string>;
};

export type SectionEvidenceResponse = {
  contract_version?: string;
  evidence: StandaloneEvidenceResult;
};

export type SelectedEventResponse = {
  disaster: string;
  event_id: string;
  event_time: string;
  geography_status: string;
  geometry?: EventGeometryResponse | null;
  lineage_ids?: Array<string>;
  location: string;
  location_source?: SourceResponse | null;
  measurements?: Array<EventMeasurementResponse>;
  provider_ids?: Array<string>;
  source: SourceResponse;
  supplemental_geometry?: Array<CycloneMapLayerResponse>;
};

export type Sensor = 'sentinel-1' | 'sentinel-2';

export type SetTimeWindowOperatorActionResponse = {
  action_id: string;
  action_type: 'set_time_window';
  label: string;
  operation: 'set';
  risk: 'automatic';
  target: 'time_window';
  value: '1h' | '6h' | '24h' | '48h' | '7d';
};

export type ShowLayerOperatorActionResponse = {
  action_id: string;
  action_type: 'show_layer';
  label: string;
  operation: 'show';
  risk: 'automatic';
  target: 'map_layer';
  value:
    | 'active-incidents'
    | 'satellite-imagery'
    | 'cop-evidence'
    | 'cyclone-supplemental'
    | 'authoritative-weather-alerts'
    | 'compound-correlations';
};

export type SourceAuthority =
  | 'national_authority'
  | 'scientific_authority'
  | 'humanitarian_aggregator'
  | 'secondary';

export type SourceCatalogItemResponse = {
  access_model?: 'public' | 'free_account' | 'self_hosted' | 'paid' | null;
  attribution: string;
  authority: string;
  country_codes?: Array<string> | null;
  coverage_description: string;
  documentation_path?: string | null;
  freshness_semantics: string;
  geographic_scopes?: Array<'country' | 'worldwide'>;
  information_roles?: Array<string>;
  license_name?: string | null;
  limitations?: Array<string>;
  operational_state: SourceOperationalStateResponse;
  provider: string;
  publisher: string;
  rights_id?: string | null;
  rights_reviewed_at?: string | null;
  source_id: string;
  stale_threshold_seconds?: number | null;
  supported_disasters?: Array<Disaster>;
};

export type SourceCatalogResponse = {
  catalog_version: string;
  sources?: Array<SourceCatalogItemResponse>;
};

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

export type SourceOperationalStateResponse = {
  availability: 'available' | 'unconfigured' | 'maintained_only';
  availability_detail: string;
  configured: boolean;
  execution_roles?: Array<string>;
  provider_tier?: 'primary' | 'secondary' | null;
  registered: boolean;
};

export type SourceReference = {
  authority?: SourceAuthority;
  canonical_url: string;
  publication_precision?: 'exact' | 'day' | 'unknown';
  published_at: string | null;
  publisher: string;
  retrieved_at: string;
  snapshot_id?: string | null;
  source_id: string;
  title: string;
  updated_at: string | null;
};

export type SourceResponse = {
  authority?: SourceAuthority;
  canonical_url: string;
  publication_precision?: 'exact' | 'day' | 'unknown';
  published_at?: string | null;
  publisher: string;
  retrieved_at: string;
  snapshot_id?: string | null;
  source_age_seconds?: number | null;
  source_id: string;
  title: string;
  updated_at?: string | null;
};

export type StandaloneEvidenceResult = {
  baseline?: BaselineVulnerabilityContext | null;
  event_id: string;
  exposure?: ExposureAnalysis | null;
  facts?: Array<ReportedFact>;
  forecast_layers?: Array<CycloneMapLayer>;
  humanitarian?: HumanitarianContextSnapshot | null;
  limitations?: Array<string>;
  media?: DisasterMediaGallery | null;
  narratives?: Array<string>;
  physical_event_id: string;
  reason_codes?: Array<string>;
  reported_accounts?: Array<ReportedImpact>;
  retrieved_at: string;
  section: 'impacts' | 'warnings' | 'forecast' | 'exposure' | 'humanitarian' | 'media';
  state: 'available' | 'empty' | 'unconfigured' | 'degraded' | 'error';
  warnings?: Array<AssociatedWarning>;
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

export type WarningAssociation = {
  basis: WarningAssociationBasis;
  confirmed: boolean;
  event_id: string;
  rationale: string;
  warning_identifier: string;
};

export type WarningAssociationBasis = 'explicit_incident_id' | 'time_and_geometry';

export type WarningCertainty =
  'observed' | 'likely' | 'possible' | 'unlikely' | 'unknown';

export type WarningSeverity = 'extreme' | 'severe' | 'moderate' | 'minor' | 'unknown';

export type WarningUrgency = 'immediate' | 'expected' | 'future' | 'past' | 'unknown';

export type WeatherAlertCoordinateResponse = {
  latitude: number;
  longitude: number;
};

export type WeatherAlertCoverageResponse = {
  detail: string;
  geographic_scope: string;
  limitations?: Array<string>;
  publisher: string;
  source_id: string;
  state: 'alerts_found' | 'no_active_alerts' | 'degraded' | 'unavailable';
};

export type WeatherAlertGeometryResponse = {
  kind?: 'polygon';
  rings?: Array<Array<WeatherAlertCoordinateResponse>>;
};

export type WeatherAlertResponse = {
  affected_area: string;
  attribution: string;
  canonical_url?: string | null;
  certainty: 'observed' | 'likely' | 'possible' | 'unlikely' | 'unknown';
  effective?: string | null;
  event: string;
  event_codes?: Array<Array<string>>;
  expires?: string | null;
  geometry?: WeatherAlertGeometryResponse | null;
  headline?: string | null;
  languages?: Array<string>;
  lifecycle_state: 'active' | 'expired' | 'cancelled';
  limitations?: Array<string>;
  message_type: string;
  onset?: string | null;
  profile?: string | null;
  provider_alert_id: string;
  publisher: string;
  retrieved_at: string;
  scope: string;
  sender: string;
  sent?: string | null;
  severity: 'extreme' | 'severe' | 'moderate' | 'minor' | 'unknown';
  signature_present?: boolean;
  signature_verified?: boolean | null;
  source_id: string;
  status: string;
  superseded_identifiers?: Array<string>;
  urgency: 'immediate' | 'expected' | 'future' | 'past' | 'unknown';
};

export type WeatherAlertsSnapshotResponse = {
  alerts?: Array<WeatherAlertResponse>;
  coverage: WeatherAlertCoverageResponse;
  retrieved_at: string;
  warnings?: Array<WeatherAlertWarningResponse>;
};

export type WeatherAlertWarningResponse = {
  detail: string;
  partial: boolean;
  reason_code: string;
  retryable: boolean;
};

export type WorldwideIncidentWatchScopeRequest = {
  kind: 'worldwide';
};
