import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

const layoutPath = join(process.cwd(), 'src/app/layout.tsx');
const layout = readFileSync(layoutPath, 'utf8');
const styles = [...layout.matchAll(/import ['"](.+\.css)['"];?/g)]
  .map((match) => readFileSync(resolve(dirname(layoutPath), match[1]), 'utf8'))
  .join('\n');

describe('responsive layout safeguards', () => {
  it('keeps the mobile header compact and reserves space for bottom navigation', () => {
    const mobileHeaderHeight = styles.match(
      /@media \(max-width: 700px\)[\s\S]*?:root\s*{\s*--header-height:\s*(\d+)px;/,
    )?.[1];

    expect(Number(mobileHeaderHeight)).toBe(64);
    expect(styles).toMatch(/\.mobile-navigation\s*{[^}]*display: grid;/);
  });

  it('allows long selected-incident titles to wrap inside the summary', () => {
    expect(styles).toMatch(/\.selected-incident-copy\s*{[^}]*min-width: 0;/);
    expect(styles).toMatch(
      /\.selected-incident-copy h3\s*{[^}]*overflow-wrap: anywhere;/,
    );
  });

  it('compacts the assistant empty state on short desktop viewports', () => {
    expect(styles).toMatch(
      /@media \(min-width: 851px\) and \(max-height: 800px\)[\s\S]*?\.empty-state\s*{[^}]*gap: 10px;[^}]*padding: 14px 12px;/,
    );
    expect(styles).toMatch(
      /@media \(min-width: 851px\) and \(max-height: 800px\)[\s\S]*?\.assistant-starters\s*{[^}]*margin-top: 4px;/,
    );
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
