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
});
