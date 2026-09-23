export type FieldReportReviewState =
  | 'pending_review'
  | 'retained_unverified'
  | 'rejected'
  | 'associated'
  | 'admitted_operator_observation';

export type FieldReportReviewDecision =
  'reject' | 'retain_unverified' | 'associate_to_event' | 'admit_operator_observation';

export type FieldReport = {
  report_id: string;
  report_type: string;
  text: string;
  captured_at: string;
  source_created_at: string;
  received_at: string;
  submitter_channel: string;
  geometry: {
    kind: 'point' | 'polygon';
    coordinates: { longitude: number; latitude: number }[];
  };
  location_precision: 'exact' | 'approximate' | 'unknown';
  location_uncertainty_m: number | null;
  media: {
    media_id: string;
    original_filename: string;
    media_type: 'image/jpeg' | 'image/png';
    transformations: string[];
    retention_expires_at: string;
  }[];
  import_provenance: {
    source_system: string;
    source_record_id: string;
    external_verification: string | null;
    verification_inherited: false;
  } | null;
  review_state: FieldReportReviewState;
  authority: 'unverified';
  tags: string[];
  associated_event_id: string | null;
  review_revision: number;
};

export type NewFieldReportRequest = {
  report_type: string;
  text: string;
  captured_at: string;
  source_created_at: string;
  submitter_channel: string;
  geometry: {
    type: 'Point' | 'Polygon';
    coordinates: number[] | number[][][];
  };
  location_precision: 'exact' | 'approximate' | 'unknown';
  location_uncertainty_m: number | null;
  attachments: {
    filename: string;
    media_type: 'image/jpeg' | 'image/png';
    content_base64: string;
  }[];
};

export type FieldReportReviewRequest = {
  decision: FieldReportReviewDecision;
  rationale: string;
  event_id: string | null;
  authority_policy_id: string | null;
};

export type FieldReviewCapability = {
  available: boolean;
  reason: 'not_configured' | 'identity_missing' | null;
};

export type FieldReportReviewOutcome = {
  report: FieldReport;
  review: {
    review_id: string;
    report_id: string;
    decision: FieldReportReviewDecision;
    reviewer_id: string;
    rationale: string;
    reviewed_at: string;
    event_id: string | null;
    authority_policy_id: string | null;
    revision: number;
  };
  operator_observation: {
    observation_id: string;
    source_report_id: string;
    event_id: string;
    authority: 'operator_observation';
  } | null;
};

export type FieldReportDuplicateCandidate = {
  candidate_id: string;
  report_ids: [string, string];
  time_delta_seconds: number;
  distance_km: number;
  same_type: boolean;
  score: number;
  auto_merge: false;
};
