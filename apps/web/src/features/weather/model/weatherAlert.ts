export type WeatherAlertSeverity =
  'extreme' | 'severe' | 'moderate' | 'minor' | 'unknown';
export type WeatherAlertUrgency =
  'immediate' | 'expected' | 'future' | 'past' | 'unknown';
export type WeatherAlertCertainty =
  'observed' | 'likely' | 'possible' | 'unlikely' | 'unknown';

export type WeatherAlertCoordinate = {
  latitude: number;
  longitude: number;
};

export type WeatherAlertGeometry = {
  kind: 'polygon';
  rings: WeatherAlertCoordinate[][];
};

export type WeatherAlert = {
  provider_alert_id: string;
  source_id: string;
  publisher: string;
  event: string;
  headline: string | null;
  severity: WeatherAlertSeverity;
  urgency: WeatherAlertUrgency;
  certainty: WeatherAlertCertainty;
  sent: string | null;
  effective: string | null;
  onset: string | null;
  expires: string | null;
  affected_area: string;
  geometry: WeatherAlertGeometry | null;
  canonical_url: string | null;
  retrieved_at: string;
  attribution: string;
  limitations: string[];
};

export type WeatherAlertCoverageState =
  'alerts_found' | 'no_active_alerts' | 'degraded' | 'unavailable';

export type WeatherAlertsSnapshot = {
  retrieved_at: string;
  alerts: WeatherAlert[];
  coverage: {
    source_id: string;
    publisher: string;
    state: WeatherAlertCoverageState;
    detail: string;
    geographic_scope: string;
    limitations: string[];
  };
  warnings: {
    reason_code: string;
    detail: string;
    retryable: boolean;
    partial: boolean;
  }[];
};
