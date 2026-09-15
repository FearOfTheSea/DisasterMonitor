import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { AuthorityWarningList } from '@/features/weather/ui/AuthorityWarningList';
import type { WeatherAlert } from '@/features/weather/model/weatherAlert';

const base: WeatherAlert = {
  provider_alert_id: 'warning-1',
  source_id: 'meteoalarm-warnings',
  publisher: 'ZAMG Austria',
  sender: 'zamg.at',
  event: 'Severe Rain Warning',
  headline: 'Rain warning',
  severity: 'severe',
  urgency: 'expected',
  certainty: 'likely',
  sent: '2026-09-15T00:00:00Z',
  effective: '2026-09-15T01:00:00Z',
  onset: null,
  expires: '2026-09-15T10:00:00Z',
  affected_area: 'Vienna',
  geometry: null,
  canonical_url: 'https://feeds.meteoalarm.org/cap/warning-1.xml',
  retrieved_at: '2026-09-15T00:05:00Z',
  attribution: 'MeteoAlarm',
  limitations: [],
  status: 'actual',
  message_type: 'alert',
  scope: 'public',
  lifecycle_state: 'active',
  languages: ['de-AT', 'en'],
  event_codes: [],
  superseded_identifiers: [],
  profile: 'CAP 1.2 / MeteoAlarm Atom',
  signature_present: false,
  signature_verified: null,
};

afterEach(cleanup);

describe('AuthorityWarningList', () => {
  it('filters on authority-first CAP dimensions and always shows issuer/validity', () => {
    render(
      <AuthorityWarningList
        alerts={[
          base,
          {
            ...base,
            provider_alert_id: 'warning-2',
            source_id: 'noaa-tsunami-warnings',
            publisher: 'NOAA Pacific Tsunami Warning Center',
            sender: 'ptwc@noaa.gov',
            event: 'Tsunami Warning',
            severity: 'extreme',
            urgency: 'immediate',
            certainty: 'observed',
            lifecycle_state: 'cancelled',
          },
        ]}
      />,
    );

    expect(screen.getByText(/Issuer: ZAMG Austria/i)).toBeInTheDocument();
    expect(screen.getAllByText(/Valid:/i)).toHaveLength(2);
    fireEvent.change(screen.getByLabelText('Warning state'), {
      target: { value: 'cancelled' },
    });
    expect(screen.queryByText('Severe Rain Warning')).not.toBeInTheDocument();
    expect(screen.getByText('Tsunami Warning')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Warning severity'), {
      target: { value: 'severe' },
    });
    expect(screen.getByText(/No warnings match/i)).toBeInTheDocument();
  });
});
