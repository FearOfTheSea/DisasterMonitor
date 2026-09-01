import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

const styles = readFileSync(join(process.cwd(), 'src/app/globals.css'), 'utf8');

describe('responsive layout safeguards', () => {
  it('reserves enough mobile header height for the brand and two action rows', () => {
    const mobileHeaderHeight = styles.match(
      /@media \(max-width: 700px\)[\s\S]*?:root\s*{\s*--header-height:\s*(\d+)px;/,
    )?.[1];

    expect(Number(mobileHeaderHeight)).toBeGreaterThanOrEqual(144);
  });

  it('keeps sparse Source Catalog content packed at the top', () => {
    expect(styles).toMatch(/\.source-catalog-scroll\s*{[^}]*align-content: start;/);
  });

  it('uses the map controls as the single scroll surface for weather alerts', () => {
    expect(styles).toMatch(
      /\.weather-alerts-legend\s*{[^}]*max-height: none;[^}]*overflow-y: visible;/,
    );
  });

  it('locks the mobile workspace behind an open full-screen panel', () => {
    expect(styles).toMatch(
      /\.workspace-assistant-open,\s*\.workspace-operations-open,\s*\.workspace-source-catalog-open\s*{[^}]*height: calc\(100dvh - var\(--header-height\)\);[^}]*overflow: hidden;/,
    );
  });
});
