import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { SearchPage } from "@/pages/SearchPage";
import * as usePacketsModule from "@/hooks/usePackets";
import * as useSearchModule from "@/hooks/useSearch";
import type { Packet, SearchResponse } from "@/types/api";

const mockPackets: Packet[] = [
  {
    id: "packet-123",
    name: "Acme Litigation Exhibits",
    description: "Trial exhibits set",
    bates_prefix: "ACME-",
    bates_start_number: 1,
    bates_padding: 6,
    created_at: "2026-08-01T10:00:00Z",
    updated_at: "2026-08-02T10:00:00Z",
    status: "completed",
    document_count: 5,
    total_pages: 50,
  },
];

const mockSearchResponse: SearchResponse = {
  packet_id: "packet-123",
  query: "Confidential settlement",
  total_results: 1,
  results: [
    {
      document_id: "doc-1",
      document_name: "Settlement_Agreement.pdf",
      document_type: "pdf" as any,
      page_count: 5,
      status: "completed",
      matched_fields: ["content", "ocr"],
      snippets: [
        {
          page_number: 2,
          bates_label: "ACME-000002",
          snippet: "This Confidential settlement agreement is entered into between the parties.",
        },
      ],
    },
  ],
};

function renderSearchPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <SearchPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("SearchPage Component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(usePacketsModule, "usePackets").mockReturnValue({
      data: mockPackets,
      isLoading: false,
      error: null,
    } as any);

    vi.spyOn(useSearchModule, "useSearchPacket").mockImplementation((packetId: string, query: string) => {
      if (packetId && query) {
        return {
          data: mockSearchResponse,
          isLoading: false,
          error: null,
          refetch: vi.fn(),
        } as any;
      }
      return {
        data: undefined,
        isLoading: false,
        error: null,
        refetch: vi.fn(),
      } as any;
    });
  });

  it("renders the page title and search prompt", async () => {
    renderSearchPage();
    expect(screen.getByRole("heading", { name: "Packet Search" })).toBeInTheDocument();
    expect(screen.getByText(/E-Discovery Intelligence/i)).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/Search filenames, extracted content, or Bates numbers/i)).toBeInTheDocument();
  });

  it("renders suggested search query chips", async () => {
    renderSearchPage();
    expect(screen.getByText("Acute Bronchitis")).toBeInTheDocument();
    expect(screen.getByText("Jane Smith")).toBeInTheDocument();
    expect(screen.getByText("Confidential settlement")).toBeInTheDocument();
  });

  it("executes search and displays matching snippets", async () => {
    renderSearchPage();

    // Select packet
    const select = screen.getByRole("combobox");
    fireEvent.change(select, { target: { value: "packet-123" } });

    // Type query
    const input = screen.getByPlaceholderText(/Search filenames, extracted content, or Bates numbers/i);
    fireEvent.change(input, { target: { value: "Confidential settlement" } });

    // Submit form
    const form = input.closest("form")!;
    fireEvent.submit(form);

    // Verify search results appear
    expect(await screen.findByText("Settlement_Agreement.pdf")).toBeInTheDocument();
    expect(screen.getByText("Page 2")).toBeInTheDocument();
    expect(screen.getByText(/This Confidential settlement agreement is entered into between the parties/i)).toBeInTheDocument();
    expect(screen.getByText(/Found/i)).toBeInTheDocument();
  });

  it("updates query when clicking suggested chip", async () => {
    renderSearchPage();

    const chip = screen.getByText("ACC-8821-4433");
    fireEvent.click(chip);

    const input = screen.getByPlaceholderText(/Search filenames, extracted content, or Bates numbers/i) as HTMLInputElement;
    expect(input.value).toBe("ACC-8821-4433");
  });
});
