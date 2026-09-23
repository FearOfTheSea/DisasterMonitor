'use client';

import { FormEvent, useCallback, useEffect, useState } from 'react';

import {
  createFieldReport,
  fetchDuplicateCandidates,
  fetchFieldReports,
  fetchFieldReviewCapability,
  reviewFieldReport,
} from '@/features/operations/api/fieldReportsClient';
import type {
  FieldReport,
  FieldReportDuplicateCandidate,
  FieldReportReviewDecision,
  NewFieldReportRequest,
} from '@/shared/types/fieldReports';

type FieldReportWorkbenchProps = {
  selectedIncidentId?: string;
};

type GeometryMode = 'point' | 'polygon';

type ReviewDraft = {
  decision: FieldReportReviewDecision;
  rationale: string;
};

const EMPTY_REVIEW: ReviewDraft = {
  decision: 'retain_unverified',
  rationale: '',
};

function datetimeLocalNow() {
  const now = new Date();
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

function toIsoDatetime(value: string) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) throw new Error('Enter valid report times.');
  return parsed.toISOString();
}

function parsePolygon(value: string): number[][][] {
  const ring = value
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => line.split(',').map((part) => Number(part.trim())));
  if (
    ring.length < 4 ||
    ring.some(
      (coordinate) =>
        coordinate.length !== 2 || coordinate.some((value) => !Number.isFinite(value)),
    ) ||
    ring[0][0] !== ring.at(-1)?.[0] ||
    ring[0][1] !== ring.at(-1)?.[1]
  ) {
    throw new Error(
      'Polygon needs at least four longitude,latitude lines and must close.',
    );
  }
  return [ring];
}

async function attachmentRequest(file: File | null) {
  if (!file) return [];
  if (file.type !== 'image/jpeg' && file.type !== 'image/png') {
    throw new Error('Attach a JPEG or PNG image only.');
  }
  if (file.size > 8_000_000) {
    throw new Error('Field attachment must be 8 MB or smaller.');
  }
  const mediaType: 'image/jpeg' | 'image/png' = file.type;
  const content = await file.arrayBuffer();
  const bytes = new Uint8Array(content);
  let binary = '';
  for (let offset = 0; offset < bytes.length; offset += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
  }
  return [
    {
      filename: file.name,
      media_type: mediaType,
      content_base64: window.btoa(binary),
    },
  ];
}

export function FieldReportWorkbench({
  selectedIncidentId,
}: FieldReportWorkbenchProps) {
  const [reports, setReports] = useState<FieldReport[]>([]);
  const [duplicates, setDuplicates] = useState<FieldReportDuplicateCandidate[]>([]);
  const [reportType, setReportType] = useState('road_blocked');
  const [text, setText] = useState('');
  const [capturedAt, setCapturedAt] = useState(datetimeLocalNow);
  const [sourceCreatedAt, setSourceCreatedAt] = useState(datetimeLocalNow);
  const [geometryMode, setGeometryMode] = useState<GeometryMode>('point');
  const [longitude, setLongitude] = useState('');
  const [latitude, setLatitude] = useState('');
  const [polygon, setPolygon] = useState('');
  const [locationPrecision, setLocationPrecision] = useState<
    'exact' | 'approximate' | 'unknown'
  >('approximate');
  const [uncertainty, setUncertainty] = useState('100');
  const [attachment, setAttachment] = useState<File | null>(null);
  const [reviewDrafts, setReviewDrafts] = useState<Record<string, ReviewDraft>>({});
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [reviewCapability, setReviewCapability] = useState<{
    available: boolean;
    reason: string | null;
  }>({ available: false, reason: 'checking' });

  const refresh = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    try {
      const [nextReports, nextDuplicates, capability] = await Promise.all([
        fetchFieldReports(signal),
        fetchDuplicateCandidates(signal),
        fetchFieldReviewCapability(signal),
      ]);
      setReports(nextReports);
      setDuplicates(nextDuplicates);
      setReviewCapability(capability);
      setError(null);
    } catch (caught) {
      setReviewCapability({ available: false, reason: 'unavailable' });
      if (!(caught instanceof DOMException && caught.name === 'AbortError')) {
        setError(
          caught instanceof Error ? caught.message : 'Field reports failed to load.',
        );
      }
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => void refresh(controller.signal), 0);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [refresh]);

  async function submitReport(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setStatus('Submitting…');
    setError(null);
    try {
      const point = [Number(longitude), Number(latitude)];
      if (
        geometryMode === 'point' &&
        (longitude.trim() === '' || latitude.trim() === '' || point.some(Number.isNaN))
      ) {
        throw new Error('Point reports require a longitude and latitude.');
      }
      const body: NewFieldReportRequest = {
        report_type: reportType,
        text: text.trim(),
        captured_at: toIsoDatetime(capturedAt),
        source_created_at: toIsoDatetime(sourceCreatedAt),
        submitter_channel: 'operator-form',
        geometry:
          geometryMode === 'point'
            ? { type: 'Point', coordinates: point }
            : { type: 'Polygon', coordinates: parsePolygon(polygon) },
        location_precision: locationPrecision,
        location_uncertainty_m:
          locationPrecision === 'approximate' ? Number(uncertainty) : null,
        attachments: await attachmentRequest(attachment),
      };
      await createFieldReport(body);
      setText('');
      setAttachment(null);
      setStatus('Report queued as unverified.');
      await refresh();
    } catch (caught) {
      setStatus(null);
      setError(caught instanceof Error ? caught.message : 'Report submission failed.');
    }
  }

  function updateReview(reportId: string, update: Partial<ReviewDraft>) {
    setReviewDrafts((current) => ({
      ...current,
      [reportId]: { ...(current[reportId] ?? EMPTY_REVIEW), ...update },
    }));
  }

  async function submitFieldReview(reportId: string) {
    const draft = reviewDrafts[reportId] ?? EMPTY_REVIEW;
    const needsEvent = ['associate_to_event', 'admit_operator_observation'].includes(
      draft.decision,
    );
    if (needsEvent && !selectedIncidentId) {
      setError('Select an incident before associating or admitting a report.');
      return;
    }
    try {
      setError(null);
      setStatus('Recording review…');
      await reviewFieldReport(reportId, {
        decision: draft.decision,
        rationale: draft.rationale.trim(),
        event_id: needsEvent ? (selectedIncidentId ?? null) : null,
        authority_policy_id:
          draft.decision === 'admit_operator_observation'
            ? 'operator-observation-admission.v1'
            : null,
      });
      setStatus('Field report review recorded.');
      await refresh();
    } catch (caught) {
      setStatus(null);
      setError(
        caught instanceof Error ? caught.message : 'Review could not be recorded.',
      );
    }
  }

  const duplicateReportIds = new Set(duplicates.flatMap((item) => item.report_ids));

  return (
    <section className="operations-section field-report-workbench">
      <div className="operations-heading">
        <div>
          <h3>Field reports</h3>
          <p>
            Operator submissions remain unverified until an explicit review decision.
          </p>
        </div>
        <button type="button" onClick={() => void refresh()} disabled={loading}>
          Refresh
        </button>
      </div>

      <details>
        <summary>Add field report</summary>
        <form className="field-report-form" onSubmit={submitReport}>
          <label>
            <span>Report type</span>
            <select
              aria-label="Report type"
              value={reportType}
              onChange={(event) => setReportType(event.target.value)}
            >
              <option value="road_blocked">Road blocked</option>
              <option value="flooding">Flooding</option>
              <option value="infrastructure_damage">Infrastructure damage</option>
              <option value="medical_need">Medical need</option>
              <option value="other">Other</option>
            </select>
          </label>
          <label className="field-report-wide">
            <span>Report text</span>
            <textarea
              aria-label="Field report text"
              required
              maxLength={10_000}
              rows={3}
              value={text}
              onChange={(event) => setText(event.target.value)}
            />
          </label>
          <label>
            <span>Captured at</span>
            <input
              aria-label="Captured at"
              required
              type="datetime-local"
              value={capturedAt}
              onChange={(event) => setCapturedAt(event.target.value)}
            />
          </label>
          <label>
            <span>Source created at</span>
            <input
              aria-label="Source created at"
              required
              type="datetime-local"
              value={sourceCreatedAt}
              onChange={(event) => setSourceCreatedAt(event.target.value)}
            />
          </label>
          <label>
            <span>Geometry</span>
            <select
              value={geometryMode}
              onChange={(event) => setGeometryMode(event.target.value as GeometryMode)}
            >
              <option value="point">Point</option>
              <option value="polygon">Polygon</option>
            </select>
          </label>
          {geometryMode === 'point' ? (
            <>
              <label>
                <span>Longitude</span>
                <input
                  aria-label="Longitude"
                  inputMode="decimal"
                  value={longitude}
                  onChange={(event) => setLongitude(event.target.value)}
                />
              </label>
              <label>
                <span>Latitude</span>
                <input
                  aria-label="Latitude"
                  inputMode="decimal"
                  value={latitude}
                  onChange={(event) => setLatitude(event.target.value)}
                />
              </label>
            </>
          ) : (
            <label className="field-report-wide">
              <span>Polygon coordinates · one longitude,latitude pair per line</span>
              <textarea
                rows={5}
                value={polygon}
                onChange={(event) => setPolygon(event.target.value)}
                placeholder={'106.0,21.0\n106.2,21.0\n106.2,21.2\n106.0,21.0'}
              />
            </label>
          )}
          <label>
            <span>Location precision</span>
            <select
              value={locationPrecision}
              onChange={(event) =>
                setLocationPrecision(
                  event.target.value as 'exact' | 'approximate' | 'unknown',
                )
              }
            >
              <option value="approximate">Approximate</option>
              <option value="exact">Exact</option>
              <option value="unknown">Unknown</option>
            </select>
          </label>
          {locationPrecision === 'approximate' && (
            <label>
              <span>Uncertainty (metres)</span>
              <input
                aria-label="Location uncertainty in metres"
                min="1"
                max="100000"
                type="number"
                value={uncertainty}
                onChange={(event) => setUncertainty(event.target.value)}
              />
            </label>
          )}
          <label className="field-report-wide">
            <span>Image · EXIF and embedded text metadata are removed</span>
            <input
              accept="image/jpeg,image/png"
              type="file"
              onChange={(event) => setAttachment(event.target.files?.[0] ?? null)}
            />
          </label>
          <p className="field-report-boundary">
            Authority: unverified · source time, receipt time, channel, uncertainty,
            media lineage, and retention are preserved.
          </p>
          <button type="submit" disabled={!text.trim()}>
            Submit unverified report
          </button>
        </form>
      </details>

      <div className="field-report-queue">
        {!reviewCapability.available && (
          <p role="status">
            {reviewCapability.reason === 'identity_missing'
              ? 'Review requires a trusted operator identity from the configured proxy.'
              : 'Review is unavailable until a trusted operator identity proxy is configured.'}
          </p>
        )}
        {reports.map((report) => {
          const draft = reviewDrafts[report.report_id] ?? EMPTY_REVIEW;
          return (
            <article className="field-report-card" key={report.report_id}>
              <div className="field-report-card-heading">
                <strong>{report.report_type.replaceAll('_', ' ')}</strong>
                <span>{report.authority}</span>
              </div>
              <p>{report.text}</p>
              <small>
                Captured {new Date(report.captured_at).toLocaleString()} ·{' '}
                {report.location_precision}
                {report.location_uncertainty_m
                  ? ` ±${report.location_uncertainty_m}m`
                  : ''}
              </small>
              <small>
                Channel: {report.submitter_channel} · Review: {report.review_state}
              </small>
              {report.import_provenance && (
                <small>
                  Imported from {report.import_provenance.source_system} record{' '}
                  {report.import_provenance.source_record_id}; external verification was
                  not inherited.
                </small>
              )}
              {duplicateReportIds.has(report.report_id) && (
                <strong className="duplicate-candidate">
                  Possible duplicate · never auto-merged
                </strong>
              )}
              <div className="field-report-review">
                <label>
                  <span>Decision</span>
                  <select
                    aria-label={`Review decision for ${report.report_id}`}
                    value={draft.decision}
                    disabled={!reviewCapability.available}
                    onChange={(event) =>
                      updateReview(report.report_id, {
                        decision: event.target.value as FieldReportReviewDecision,
                      })
                    }
                  >
                    <option value="retain_unverified">Retain unverified</option>
                    <option value="reject">Reject</option>
                    <option value="associate_to_event">
                      Associate to selected event
                    </option>
                    <option value="admit_operator_observation">
                      Admit operator observation
                    </option>
                  </select>
                </label>
                <textarea
                  aria-label={`Review rationale for ${report.report_id}`}
                  maxLength={2_000}
                  rows={2}
                  placeholder="Required rationale"
                  value={draft.rationale}
                  disabled={!reviewCapability.available}
                  onChange={(event) =>
                    updateReview(report.report_id, { rationale: event.target.value })
                  }
                />
                <button
                  type="button"
                  disabled={!reviewCapability.available || !draft.rationale.trim()}
                  onClick={() => void submitFieldReview(report.report_id)}
                >
                  Record field report review
                </button>
              </div>
            </article>
          );
        })}
        {!loading && reports.length === 0 && <p>No field reports await review.</p>}
      </div>
      {status && <p role="status">{status}</p>}
      {error && <p role="alert">{error}</p>}
    </section>
  );
}
