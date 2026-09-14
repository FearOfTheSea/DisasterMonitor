export type DataAgeKind =
  'source' | 'projection' | 'imagery_capture' | 'forecast_validity' | 'retrieved';

type DataAgeBadgeProps = {
  kind: DataAgeKind;
  timestamp?: string | null;
  ageSeconds?: number | null;
  state?: string | null;
  label?: string;
};

const KIND_LABELS: Record<DataAgeKind, string> = {
  source: 'Source evidence',
  projection: 'Monitoring projection',
  imagery_capture: 'Imagery capture',
  forecast_validity: 'Forecast validity',
  retrieved: 'Retrieved',
};

function formatAge(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s old`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m old`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `${hours}h ${minutes % 60}m old`;
  return `${Math.floor(hours / 24)}d old`;
}

function formatTimestamp(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

export function DataAgeBadge({
  kind,
  timestamp,
  ageSeconds,
  state,
  label,
}: DataAgeBadgeProps) {
  const status = state ?? 'unknown';
  const stale = ['stale', 'degraded', 'unavailable', 'misconfigured'].includes(status);
  const value =
    ageSeconds !== null && ageSeconds !== undefined
      ? formatAge(Math.max(0, ageSeconds))
      : timestamp
        ? formatTimestamp(timestamp)
        : 'Not available';
  return (
    <span
      className={`data-age-badge${stale ? ' data-age-badge-stale' : ''}`}
      data-age-kind={kind}
      title={
        timestamp ? `${KIND_LABELS[kind]}: ${formatTimestamp(timestamp)}` : undefined
      }
    >
      <strong>{label ?? KIND_LABELS[kind]}</strong>
      <time dateTime={timestamp ?? undefined}>{value}</time>
    </span>
  );
}
