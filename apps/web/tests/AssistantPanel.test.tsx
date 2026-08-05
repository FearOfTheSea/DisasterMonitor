import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { AssistantPanel } from '@/features/assistant/ui/AssistantPanel';

describe('AssistantPanel', () => {
  it('submits a question and renders the conversation', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(
      <AssistantPanel
        messages={[{ id: 'a1', role: 'assistant', content: 'Ready.' }]}
        status="idle"
        error={null}
        onSubmit={onSubmit}
        onClear={vi.fn()}
      />,
    );

    await user.type(screen.getByLabelText('Question'), 'What does this map show?');
    await user.click(screen.getByRole('button', { name: 'Ask assistant' }));

    expect(onSubmit).toHaveBeenCalledWith('What does this map show?');
    expect(screen.getByText('Ready.')).toBeInTheDocument();
  });

  it('shows loading and error states', () => {
    const { rerender } = render(
      <AssistantPanel
        messages={[]}
        status="loading"
        error={null}
        onSubmit={vi.fn()}
        onClear={vi.fn()}
      />,
    );
    expect(screen.getByText('Thinking locally…')).toBeInTheDocument();

    rerender(
      <AssistantPanel
        messages={[]}
        status="error"
        error="The local backend is unavailable."
        onSubmit={vi.fn()}
        onClear={vi.fn()}
      />,
    );
    expect(screen.getByRole('alert')).toHaveTextContent('local backend');
  });

  it('renders structured report sections, warnings, links, and freshness', () => {
    render(
      <AssistantPanel
        messages={[
          {
            id: 'report-1',
            role: 'assistant',
            content: 'Source-backed report text.',
            report: {
              responseType: 'current_disaster',
              partial: true,
              warnings: ['Situation source unavailable.'],
              sections: [
                { title: 'Situation summary', content: 'A quake was identified.' },
                {
                  title: 'Physical and infrastructure damage',
                  content: 'No reliable figure yet.',
                },
              ],
              sources: [
                {
                  publisher: 'JMA',
                  title: 'Earthquake fixture',
                  canonical_url: 'https://example.test/event',
                  published_at: '2026-08-05T11:00:00Z',
                  retrieved_at: '2026-08-05T12:00:00Z',
                },
              ],
            },
          },
        ]}
        status="idle"
        error={null}
        onSubmit={vi.fn()}
        onClear={vi.fn()}
      />,
    );

    expect(
      screen.getByRole('heading', { name: 'Situation summary' }),
    ).toBeInTheDocument();
    expect(screen.getByText('Situation source unavailable.')).toBeInTheDocument();
    expect(
      screen.getByRole('link', { name: /JMA: Earthquake fixture/ }),
    ).toHaveAttribute('href', 'https://example.test/event');
    expect(screen.getByText(/Retrieved:/)).toBeInTheDocument();
  });
});
