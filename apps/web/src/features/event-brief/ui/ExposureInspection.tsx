import { useState, type FormEvent } from 'react';
import { fetchInspectionExposure } from '@/features/event-brief/api/sectionEvidenceClient';
import type { StandaloneEvidenceResult } from '@/shared/api/generated/assistant';

export function ExposureInspection({
  identifier,
  onResult,
}: {
  identifier: string;
  onResult: (evidence: StandaloneEvidenceResult) => void;
}) {
  const [bounds, setBounds] = useState(['', '', '', '']);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  async function calculate(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(undefined);
    try {
      onResult(
        await fetchInspectionExposure(
          identifier,
          bounds.map(Number) as [number, number, number, number],
        ),
      );
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : 'Exposure calculation failed.',
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <details className="exposure-inspection">
      <summary>Inspect a supplied area</summary>
      <p>
        This operator inspection rectangle is not an impact footprint. Supply WGS84
        coordinates with a diagonal of at most 60 km. Calculations require datasets
        covering the area.
      </p>
      <form onSubmit={(event) => void calculate(event)}>
        {['West longitude', 'South latitude', 'East longitude', 'North latitude'].map(
          (label, index) => (
            <label key={label}>
              {label}
              <input
                type="number"
                step="any"
                required
                value={bounds[index]}
                onChange={(event) =>
                  setBounds((current) =>
                    current.map((value, position) =>
                      position === index ? event.target.value : value,
                    ),
                  )
                }
              />
            </label>
          ),
        )}
        <button type="submit" disabled={busy}>
          {busy ? 'Calculating inspection exposure…' : 'Calculate inspection exposure'}
        </button>
        {error && <p role="alert">{error}</p>}
      </form>
    </details>
  );
}
