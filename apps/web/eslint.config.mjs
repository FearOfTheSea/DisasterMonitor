import coreWebVitals from 'eslint-config-next/core-web-vitals';
import typescript from 'eslint-config-next/typescript';
import { capabilityBoundaries } from './scripts/architecture_rules.mjs';

const config = [
  ...coreWebVitals,
  ...typescript,
  {
    files: ['src/**/*.{ts,tsx}'],
    plugins: { architecture: { rules: { boundaries: capabilityBoundaries } } },
    rules: { 'architecture/boundaries': 'error' },
  },
];

export default config;
