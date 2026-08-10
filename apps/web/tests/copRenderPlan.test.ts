import { describe, expect, it } from 'vitest';

import {
  buildCopRenderPlan,
  copStyleSemantics,
} from '@/features/map/model/copRenderPlan';
import { commonOperationalPicture } from './fixtures/multimodal';

describe('COP rendering semantics', () => {
  it('retains status, uncertainty, attribution, and analytical authority', () => {
    const plan = buildCopRenderPlan(commonOperationalPicture);

    expect(plan).toHaveLength(1);
    expect(plan[0]).toMatchObject({
      authority: 'analytical_generated',
      status: 'current',
      uncertainty: 'Analytical estimate only.',
      attribution: expect.stringContaining('Licensed operator fixture'),
    });
  });

  it('uses textual labels and distinct line patterns, not color alone', () => {
    const official = copStyleSemantics('official_source');
    const supplied = copStyleSemantics('source_supplied');
    const analytical = copStyleSemantics('analytical_generated');

    expect([
      official.patternLabel,
      supplied.patternLabel,
      analytical.patternLabel,
    ]).toEqual(['solid', 'dotted', 'dashed']);
    expect(official.authorityLabel).toBe('Official source');
    expect(analytical.authorityLabel).toContain('AI-generated');
  });
});
