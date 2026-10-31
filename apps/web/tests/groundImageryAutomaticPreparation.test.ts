import { describe, expect, it } from 'vitest';

import { automaticPreparationSelections } from '@/features/imagery/model/groundImagery';
import type {
  GroundImageryRequestResponse,
  Sensor,
} from '@/shared/api/generated/assistant';

import { comparisonRequest, observation } from './groundImageryPanelFixtures';

function unprepared(): GroundImageryRequestResponse {
  return {
    ...comparisonRequest,
    artifacts: [],
    sensors: (['sentinel-1', 'sentinel-2'] as Sensor[]).map((sensor) => ({
      ...comparisonRequest.sensors[0],
      sensor,
      selections: [
        'pre_event_reference',
        'first_useful_after_onset',
        'latest_useful',
      ].map((role) => ({
        ...comparisonRequest.sensors[0].selections[0],
        selection_id: `${sensor}:${role}`,
        sensor,
        role,
        observation: {
          ...observation(`${sensor}:${role}`, '2024-05-21T00:00:00Z'),
          sensor,
        },
      })),
    })),
  };
}

describe('Automatic imagery preparation capacity', () => {
  it('leaves hourly preparation capacity for an operator-selected capture', () => {
    const selections = automaticPreparationSelections(unprepared());
    expect(selections.map((selection) => selection.selection_id)).toEqual([
      'sentinel-1:latest_useful',
      'sentinel-2:latest_useful',
    ]);
  });

  it('does not spend more capacity on baseline captures when reopening prepared preferred views', () => {
    const request = unprepared();
    request.artifacts = request.sensors.map((sensor) => ({
      ...comparisonRequest.artifacts![0],
      selection_id: `${sensor.sensor}:latest_useful`,
      sensor: sensor.sensor,
    }));
    expect(automaticPreparationSelections(request)).toEqual([]);
  });

  it('still prepares the other sensor when one preferred view is already cached', () => {
    const request = unprepared();
    request.artifacts = [
      {
        ...comparisonRequest.artifacts![0],
        selection_id: 'sentinel-1:latest_useful',
      },
    ];
    expect(
      automaticPreparationSelections(request).map(
        (selection) => selection.selection_id,
      ),
    ).toEqual(['sentinel-2:latest_useful']);
  });
});
