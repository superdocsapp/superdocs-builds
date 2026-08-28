import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DocumentDetailPanel } from './DocumentDetailPanel';

const SOURCE_TEXT =
  'The borrower agrees to repay the principal amount of 100000 USD at 8.5% annual interest.';

function mockFetchResponse(payload: unknown, ok = true, status = 200) {
  return {
    ok,
    status,
    json: () => Promise.resolve(payload),
  };
}

const groundedFacts = {
  document_id: 'doc-1',
  document_version_id: 'ver-1',
  filename: 'loan.txt',
  classification: 'loan_agreement',
  run_id: 'run-1',
  source_text: SOURCE_TEXT,
  facts: [
    {
      field_name: 'principal_amount',
      extracted_value: 'principal amount of 100000 USD',
      confidence: 0.97,
      extraction_method: 'structured',
      citation_status: 'grounded',
      cited_span: {
        start_offset: SOURCE_TEXT.indexOf('principal amount of 100000 USD'),
        end_offset: SOURCE_TEXT.indexOf('principal amount of 100000 USD') + 30,
        snippet: 'principal amount of 100000 USD',
        page_number: null,
        section_id: null,
      },
    },
    {
      field_name: 'interest_rate',
      extracted_value: '8.5% annual interest',
      confidence: 0.9,
      extraction_method: 'llm',
      citation_status: 'grounded',
      cited_span: {
        start_offset: SOURCE_TEXT.indexOf('8.5% annual interest'),
        end_offset: SOURCE_TEXT.indexOf('8.5% annual interest') + 20,
        snippet: '8.5% annual interest',
        page_number: null,
        section_id: null,
      },
    },
    {
      field_name: 'lender_name',
      extracted_value: null, // extractor recorded not_found
      confidence: null,
      extraction_method: null,
      citation_status: 'not_found',
      cited_span: null,
    },
    {
      field_name: 'borrower_name',
      extracted_value: 'Alice Johnson',
      confidence: 0.6,
      extraction_method: 'llm',
      citation_status: 'unverifiable', // no span resolvable
      cited_span: null,
    },
  ],
};

describe('DocumentDetailPanel', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('renders every fact from the API response with method and citation', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      mockFetchResponse(groundedFacts) as Response,
    );
    render(
      <DocumentDetailPanel documentId="doc-1" filename="loan.txt" onClose={() => {}} />,
    );

    await waitFor(() => screen.getByTestId('facts-table'));

    // Field rows — including the not_found one (never silently omitted)
    expect(screen.getByTestId('fact-row-principal_amount')).toBeInTheDocument();
    expect(screen.getByTestId('fact-row-interest_rate')).toBeInTheDocument();
    expect(screen.getByTestId('fact-row-lender_name')).toBeInTheDocument();
    expect(screen.getByTestId('fact-row-borrower_name')).toBeInTheDocument();

    // Values
    expect(screen.getByText('principal amount of 100000 USD')).toBeInTheDocument();

    // Extraction methods come from the API, not invented client-side
    expect(screen.getByText('structured')).toBeInTheDocument();
    expect(screen.getAllByText('llm').length).toBeGreaterThanOrEqual(1);
    // extraction_method=null renders as "not found" in the Method column too
    const notFoundCells = screen.getAllByText('not found');
    expect(notFoundCells.length).toBeGreaterThanOrEqual(2);

    // Grounded citations show the REAL server-resolved snippet
    const grounded = screen.getAllByTestId('citation-grounded');
    expect(grounded).toHaveLength(2);
    expect(screen.getAllByText(/principal amount of 100000 USD/).length).toBeGreaterThanOrEqual(1);

    // Unverifiable marker is visually distinct (icon + label), not small text
    expect(screen.getByTestId('citation-unverifiable')).toBeInTheDocument();
    expect(screen.getByText('[citation unverifiable]')).toBeInTheDocument();

    // not_found renders explicitly (value cell + method cell)
    expect(screen.getAllByText('not found').length).toBeGreaterThanOrEqual(2);
  });

  it('raw text tab highlights exactly the server-provided spans inline', async () => {
    const user = userEvent.setup();
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      mockFetchResponse(groundedFacts) as Response,
    );
    render(
      <DocumentDetailPanel documentId="doc-1" filename="loan.txt" onClose={() => {}} />,
    );
    await waitFor(() => screen.getByTestId('facts-table'));

    await user.click(screen.getByTestId('tab-raw'));
    await waitFor(() => screen.getByTestId('raw-text-view'));

    // Both grounded spans highlighted; highlight content matches server snippet
    const highlights = screen.getAllByRole('mark');
    expect(highlights).toHaveLength(2);
    expect(highlights[0]).toHaveTextContent('principal amount of 100000 USD');
    expect(highlights[1]).toHaveTextContent('8.5% annual interest');

    // Surrounding non-cited context is present un-highlighted
    expect(screen.getByTestId('raw-text-view')).toHaveTextContent('The borrower agrees to repay the');
    expect(screen.getByTestId('raw-text-view')).toHaveTextContent('.');
  });

  it('shows an error state when the API fails', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      mockFetchResponse({ detail: 'nope' }, false, 500) as Response,
    );
    render(
      <DocumentDetailPanel documentId="doc-1" filename="loan.txt" onClose={() => {}} />,
    );
    await waitFor(() => screen.getByTestId('facts-error'));
    expect(screen.getByTestId('facts-error')).toHaveTextContent('Failed to load document facts');
  });
});
