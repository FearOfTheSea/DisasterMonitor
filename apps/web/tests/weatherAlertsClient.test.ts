import { afterEach, describe, expect, it, vi } from 'vitest';

import { fetchWeatherAlerts } from '@/features/weather/api/weatherAlertsClient';

const RESPONSE = {
  retrieved_at: '2026-09-01T02:00:00Z',
  alerts: [
    {
      provider_alert_id: 'urn:oid:fixture',
      source_id: 'nws-weather-alerts',
      publisher: 'NWS Fixture Office',
      event: 'Tornado Warning',
      headline: null,
      severity: 'unknown',
      urgency: 'immediate',
      certainty: 'observed',
      sent: '2026-09-01T01:50:00Z',
      effective: '2026-09-01T01:50:00Z',
      onset: null,
      expires: '2026-09-01T02:30:00Z',
      affected_area: 'Fixture County',
      geometry: {
        kind: 'polygon',
        rings: [
          [
            { latitude: 1, longitude: 2 },
            { latitude: 1, longitude: 3 },
            { latitude: 2, longitude: 2 },
            { latitude: 1, longitude: 2 },
          ],
        ],
      },
      canonical_url: 'https://api.weather.gov/alerts/urn:oid:fixture',
      retrieved_at: '2026-09-01T02:00:00Z',
      attribution: 'NOAA/NWS',
      limitations: ['Warning artifact only.'],
    },
  ],
  coverage: {
    source_id: 'nws-weather-alerts',
    publisher: 'NOAA/NWS',
    state: 'alerts_found',
    detail: 'One alert.',
    geographic_scope: 'United States land areas',
    limitations: ['Not global.'],
  },
  warnings: [],
};

describe('weatherAlertsClient', () => {
  afterEach(() => vi.restoreAllMocks());

  it('preserves unknown CAP values and exact source geometry', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(RESPONSE), { status: 200 }),
    );
    const snapshot = await fetchWeatherAlerts();
    expect(snapshot.alerts[0].severity).toBe('unknown');
    expect(snapshot.alerts[0].geometry?.rings[0]).toHaveLength(4);
  });

  it('rejects invented or structurally invalid geometry', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          ...RESPONSE,
          alerts: [
            {
              ...RESPONSE.alerts[0],
              geometry: { kind: 'point', coordinates: [2, 1] },
            },
          ],
        }),
        { status: 200 },
      ),
    );
    await expect(fetchWeatherAlerts()).rejects.toThrow(/invalid response|geometry/i);
  });

  it('rejects a canonical link outside the official alert origin', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          ...RESPONSE,
          alerts: [
            {
              ...RESPONSE.alerts[0],
              canonical_url: 'https://example.test/alerts/fixture',
            },
          ],
        }),
        { status: 200 },
      ),
    );
    await expect(fetchWeatherAlerts()).rejects.toThrow(/canonical URL/i);
  });
});
