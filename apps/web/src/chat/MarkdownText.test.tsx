import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { MarkdownContent } from './MarkdownText';
import { EvidenceRefContext } from './evidenceContext';

const REF = 'report:9f0aa889-fbf7-492c-9d6a-4e934e5e79d2:/finReports/0/common/proceeds';
const ANSWER = `## Вывод

Прибыль 444000 руб. [evidence:${REF}], активы 120650000 руб. [evidence:${REF}].

- Действующее производство [evidence:report:11111111-1111-1111-1111-111111111111:/executionProceedings/1/active]`;

describe('MarkdownContent', () => {
  it('renders Markdown as plain prose and never shows a raw evidence token', () => {
    render(
      <EvidenceRefContext.Provider value={vi.fn()}>
        <MarkdownContent text={ANSWER} />
      </EvidenceRefContext.Provider>,
    );
    expect(screen.queryByText(/\[evidence:/)).not.toBeInTheDocument();
    // The heading is down-levelled to bold text, not an <h2>.
    expect(screen.queryByRole('heading')).not.toBeInTheDocument();
    expect(screen.getByText('Вывод')).toBeVisible();
  });

  it('collapses each evidence token to a numbered chip that opens its basis', async () => {
    const onOpen = vi.fn();
    render(
      <EvidenceRefContext.Provider value={onOpen}>
        <MarkdownContent text={ANSWER} />
      </EvidenceRefContext.Provider>,
    );
    // The two tokens share one ref → both are basis 1; the third is basis 2.
    const first = screen.getAllByRole('button', { name: 'Основание 1' });
    expect(first).toHaveLength(2);
    expect(screen.getByRole('button', { name: 'Основание 2' })).toBeVisible();
    await userEvent.click(first[0] as HTMLElement);
    expect(onOpen).toHaveBeenCalledWith(REF);
  });

  it('shows an inert mark when no opener is provided', () => {
    render(<MarkdownContent text={ANSWER} />);
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
    expect(screen.queryByText(/\[evidence:/)).not.toBeInTheDocument();
  });
});
