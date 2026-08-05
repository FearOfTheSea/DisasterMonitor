import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests/system',
  timeout: 30_000,
  use: {
    baseURL: 'http://127.0.0.1:4173',
    trace: 'on-first-retry',
    ...devices['Desktop Chrome'],
  },
  webServer: {
    command: 'uv run --project ../api python ../../scripts/system_test_stack.py',
    cwd: '.',
    port: 4173,
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
