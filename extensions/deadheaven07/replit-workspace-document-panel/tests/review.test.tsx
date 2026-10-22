import { describe, it, expect, vi } from 'vitest';
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { ReviewTab } from '../src/components/ReviewTab';
import { ProposedChangeBatch, ProposedChange } from '../src/types/superdocs';

// @ts-expect-error configure React 18 act testing environment
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

describe('ReviewTab Component - Granular Cherry-Picking', () => {
  const mockChanges: ProposedChange[] = [
    {
      change_id: 'chg_1',
      operation: 'insert',
      new_html: '<p>New installation steps</p>',
      ai_explanation: 'Added installation instructions for CLI',
    },
    {
      change_id: 'chg_2',
      operation: 'replace',
      old_html: '<p>Old endpoint /v1/old</p>',
      new_html: '<p>New endpoint /v1/new</p>',
      ai_explanation: 'Updated API endpoint URL',
    },
    {
      change_id: 'chg_3',
      operation: 'delete',
      old_html: '<p>Deprecated auth token</p>',
      ai_explanation: 'Removed deprecated auth reference',
    },
  ];

  const mockBatch: ProposedChangeBatch = {
    batch_id: 'batch_123',
    batch_total: 3,
    changes: mockChanges,
    awaiting_kind: 'approval',
  };

  it('renders all proposed changes with selection status', () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);

    const onApprove = vi.fn();
    const onContinue = vi.fn();

    act(() => {
      root.render(
        <ReviewTab
          proposedChanges={mockBatch}
          onApprove={onApprove}
          onContinue={onContinue}
          disabled={false}
          step="awaiting_approval"
        />
      );
    });

    expect(container.textContent).toContain('3 Proposed Changes');
    expect(container.textContent).toContain('3 of 3 Selected');
    expect(container.textContent).toContain('Added installation instructions for CLI');
    expect(container.textContent).toContain('Updated API endpoint URL');
    expect(container.textContent).toContain('Removed deprecated auth reference');

    act(() => {
      root.unmount();
    });
    container.remove();
  });

  it('allows cherry-picking by deselecting an individual change', () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);

    const onApprove = vi.fn();
    const onContinue = vi.fn();

    act(() => {
      root.render(
        <ReviewTab
          proposedChanges={mockBatch}
          onApprove={onApprove}
          onContinue={onContinue}
          disabled={false}
          step="awaiting_approval"
        />
      );
    });

    const checkboxes = container.querySelectorAll<HTMLInputElement>('input[type="checkbox"]');
    expect(checkboxes.length).toBe(3);

    // Uncheck second change
    act(() => {
      checkboxes[1].click();
    });

    expect(container.textContent).toContain('2 of 3 Selected');

    // Click Approve Selected
    const approveButton = container.querySelector<HTMLButtonElement>('button[aria-label^="Approve"]');
    expect(approveButton).not.toBeNull();

    act(() => {
      approveButton?.click();
    });

    expect(onApprove).toHaveBeenCalledWith(true, [mockChanges[0], mockChanges[2]]);

    act(() => {
      root.unmount();
    });
    container.remove();
  });

  it('handles Select All and Deselect All controls correctly', () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);

    const onApprove = vi.fn();
    const onContinue = vi.fn();

    act(() => {
      root.render(
        <ReviewTab
          proposedChanges={mockBatch}
          onApprove={onApprove}
          onContinue={onContinue}
          disabled={false}
          step="awaiting_approval"
        />
      );
    });

    const deselectAllBtn = Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent?.trim() === 'Deselect All'
    );
    expect(deselectAllBtn).toBeDefined();

    act(() => {
      deselectAllBtn?.click();
    });

    expect(container.textContent).toContain('0 of 3 Selected');

    const selectAllBtn = Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent?.trim() === 'Select All'
    );
    expect(selectAllBtn).toBeDefined();

    act(() => {
      selectAllBtn?.click();
    });

    expect(container.textContent).toContain('3 of 3 Selected');

    act(() => {
      root.unmount();
    });
    container.remove();
  });
});
