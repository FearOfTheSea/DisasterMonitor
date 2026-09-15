import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, it, vi } from 'vitest';

import { AssistantPanel } from '@/features/assistant/ui/AssistantPanel';

afterEach(cleanup);

it('keeps the original source-backed report accessible after localization', async () => {
  const user = userEvent.setup();
  render(
    <AssistantPanel
      messages={[
        {
          id: 'localized-report',
          role: 'assistant',
          content: 'Báo cáo đã được bản địa hóa.',
          report: {
            responseType: 'current_disaster',
            originalMessage: 'Original source-backed report.',
            responseLanguage: 'vi',
            partial: false,
            warnings: [],
            sections: [{ title: 'Tóm tắt', content: 'Nội dung.' }],
            sources: [],
            claims: [],
            timeline: [],
          },
        },
      ]}
      status="idle"
      error={null}
      onSubmit={vi.fn()}
      onClear={vi.fn()}
    />,
  );

  expect(screen.getByText('Original source-backed report.')).not.toBeVisible();
  expect(screen.getByText(/localized to vi/)).not.toBeVisible();
  await user.click(screen.getByText('Original source-backed report text'));
  expect(screen.getByText('Original source-backed report.')).toBeVisible();
});
