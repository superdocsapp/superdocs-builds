import { describe, it, expect, vi } from 'vitest';
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { HistoryTab } from '../src/components/HistoryTab';
import { DocumentVersion } from '../src/types/superdocs';

// @ts-expect-error configure React 18 act testing environment
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

describe('HistoryTab Component (SuperDocs v2 Versions & Reverts)', () => {
  const mockVersions: DocumentVersion[] = [
    {
      version_id: 'v_1',
      document_id: 'doc_101',
      created_at: '2026-08-22T10:00:00Z',
      created_by: 'user',
      html: '<h1>Initial README</h1><p>First version content</p>',
      change_summary: 'Initial document generation',
      is_current: false,
    },
    {
      version_id: 'v_2',
      document_id: 'doc_101',
      created_at: '2026-08-22T11:00:00Z',
      created_by: 'user',
      html: '<h1>Updated README</h1><p>Revised API section</p>',
      change_summary: 'Added API endpoints',
      is_current: true,
    },
  ];

  it('renders empty state when no documentId is active', () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);

    act(() => {
      root.render(
        <HistoryTab
          documentId={undefined}
          onLoadVersions={vi.fn()}
          onLoadVersion={vi.fn()}
          onRevert={vi.fn()}
        />
      );
    });

    expect(container.textContent).toContain('No document yet');
    expect(container.textContent).toContain('Generate a document to track its version history');

    act(() => {
      root.unmount();
    });
    container.remove();
  });

  it('renders list of versions and allows preview selection', async () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);

    const onLoadVersion = vi.fn().mockResolvedValue(mockVersions[0]);

    act(() => {
      root.render(
        <HistoryTab
          documentId="doc_101"
          versions={mockVersions}
          selectedVersion={mockVersions[0]}
          onLoadVersions={vi.fn()}
          onLoadVersion={onLoadVersion}
          onRevert={vi.fn()}
        />
      );
    });

    expect(container.textContent).toContain('2 version(s) saved');
    expect(container.textContent).toContain('Initial document generation');
    expect(container.textContent).toContain('Added API endpoints');
    expect(container.textContent).toContain('Current');

    // Click preview on first version
    const previewButtons = container.querySelectorAll<HTMLButtonElement>('button');
    const previewBtn = Array.from(previewButtons).find(b => b.textContent?.includes('Preview'));
    expect(previewBtn).toBeDefined();

    await act(async () => {
      previewBtn?.click();
    });

    expect(onLoadVersion).toHaveBeenCalledWith('v_1');

    act(() => {
      root.unmount();
    });
    container.remove();
  });

  it('triggers revert callback when revert button is clicked', async () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);

    const onRevert = vi.fn().mockResolvedValue(undefined);

    act(() => {
      root.render(
        <HistoryTab
          documentId="doc_101"
          versions={mockVersions}
          onLoadVersions={vi.fn()}
          onLoadVersion={vi.fn()}
          onRevert={onRevert}
        />
      );
    });

    const revertButtons = container.querySelectorAll<HTMLButtonElement>('button');
    const revertBtn = Array.from(revertButtons).find(b => b.textContent?.includes('Revert'));
    expect(revertBtn).toBeDefined();

    await act(async () => {
      revertBtn?.click();
    });

    expect(onRevert).toHaveBeenCalledWith('v_1');

    act(() => {
      root.unmount();
    });
    container.remove();
  });
});
