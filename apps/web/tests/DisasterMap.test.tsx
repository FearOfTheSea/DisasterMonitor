import { render } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { DisasterMap } from '@/features/map/ui/DisasterMap';

const adapterMocks = vi.hoisted(() => ({
  destroy: vi.fn(),
  fitArea: vi.fn(),
  setCommonOperationalPicture: vi.fn(),
}));

vi.mock('@/features/map/adapters/openLayersMapAdapter', () => ({
  OpenLayersMapAdapter: class {
    destroy = adapterMocks.destroy;
    fitArea = adapterMocks.fitArea;
    setCommonOperationalPicture = adapterMocks.setCommonOperationalPicture;
  },
}));

describe('DisasterMap assistant focus', () => {
  it('fits each logical area once and refits when its bounds change', () => {
    const onViewChange = vi.fn();
    const { rerender, unmount } = render(
      <DisasterMap
        onViewChange={onViewChange}
        areaOfInterest={{ id: 'assistant-1:event:event-1', bounds: [137, 37, 137, 37] }}
      />,
    );

    expect(adapterMocks.fitArea).toHaveBeenCalledTimes(1);
    expect(adapterMocks.fitArea).toHaveBeenLastCalledWith([137, 37, 137, 37], 10);

    rerender(
      <DisasterMap
        onViewChange={onViewChange}
        areaOfInterest={{ id: 'assistant-1:event:event-1', bounds: [137, 37, 137, 37] }}
      />,
    );
    expect(adapterMocks.fitArea).toHaveBeenCalledTimes(1);

    rerender(
      <DisasterMap
        onViewChange={onViewChange}
        areaOfInterest={{
          id: 'assistant-1:event:event-1',
          bounds: [136, 36, 138, 38],
          maxZoom: 8,
        }}
      />,
    );
    expect(adapterMocks.fitArea).toHaveBeenCalledTimes(2);
    expect(adapterMocks.fitArea).toHaveBeenLastCalledWith([136, 36, 138, 38], 8);

    unmount();
    expect(adapterMocks.destroy).toHaveBeenCalledTimes(1);
  });
});
