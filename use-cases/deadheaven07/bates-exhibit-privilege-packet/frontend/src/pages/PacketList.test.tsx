import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { PacketList } from "@/pages/PacketList";
import { packetsApi } from "@/services/packets";
import { exportsApi } from "@/services/exports";
import { toast } from "@/components/ui/use-toast";
import type { Packet } from "@/types/api";

vi.mock("@/services/packets", () => ({
  packetsApi: {
    list: vi.fn(),
    get: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
  },
}));

vi.mock("@/services/exports", () => ({
  exportsApi: {
    build: vi.fn(),
    validate: vi.fn(),
    getManifest: vi.fn(),
    download: vi.fn(),
    downloadComponent: vi.fn(),
    listExhibits: vi.fn(),
  },
}));

vi.mock("@/components/ui/use-toast", () => ({
  toast: vi.fn(),
  useToast: () => ({ toast: vi.fn() }),
}));

const samplePackets: Packet[] = [
  {
    id: "p1",
    name: "Smith v. Jones",
    description: "Exhibit packet for trial",
    bates_prefix: "CASE-",
    bates_start_number: 1,
    bates_padding: 6,
    created_at: "2026-08-01T10:00:00Z",
    updated_at: "2026-08-02T10:00:00Z",
    document_count: 3,
    total_pages: 42,
    status: "completed",
  },
  {
    id: "p2",
    name: "Draft Packet",
    description: null,
    bates_prefix: "CASE-",
    bates_start_number: 1,
    bates_padding: 6,
    created_at: "2026-08-03T10:00:00Z",
    updated_at: "2026-08-03T10:00:00Z",
    status: "draft",
  },
];

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <PacketList />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  (packetsApi.list as ReturnType<typeof vi.fn>).mockResolvedValue(samplePackets);
});

describe("PacketList", () => {
  it("renders packets from the API", async () => {
    renderPage();
    expect(await screen.findByText("Smith v. Jones")).toBeInTheDocument();
    expect(screen.getByText("Draft Packet")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument();
  });

  it("creates a new packet through the modal", async () => {
    (packetsApi.create as ReturnType<typeof vi.fn>).mockResolvedValue({ id: "p3", name: "New Case" });
    renderPage();
    fireEvent.click(await screen.findByText("New Packet"));
    fireEvent.change(screen.getByPlaceholderText("e.g., Smith v. Jones - Exhibits"), {
      target: { value: "New Case" },
    });
    fireEvent.click(screen.getByText("Create Packet"));
    await waitFor(() => {
      expect(packetsApi.create).toHaveBeenCalledWith({ name: "New Case" });
    });
    expect(toast).toHaveBeenCalledWith(expect.objectContaining({ title: "Packet created" }));
  });

  it("opens the edit modal pre-filled and saves changes", async () => {
    (packetsApi.update as ReturnType<typeof vi.fn>).mockResolvedValue({});
    renderPage();
    const editButton = (await screen.findAllByTitle("Edit"))[0];
    fireEvent.click(editButton);
    const input = screen.getByPlaceholderText("e.g., Smith v. Jones - Exhibits") as HTMLInputElement;
    expect(input.value).toBe("Smith v. Jones");
    fireEvent.change(input, { target: { value: "Smith v. Jones (Renamed)" } });
    fireEvent.click(screen.getByText("Save Changes"));
    await waitFor(() => {
      expect(packetsApi.update).toHaveBeenCalledWith("p1", { name: "Smith v. Jones (Renamed)" });
    });
    expect(toast).toHaveBeenCalledWith(expect.objectContaining({ title: "Packet updated" }));
  });

  it("bulk exports selected packets as PDF blobs", async () => {
    (exportsApi.download as ReturnType<typeof vi.fn>).mockResolvedValue(new Blob(["%PDF"]));
    const createObjectURL = vi.fn(() => "blob:mock");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL });

    renderPage();
    const checkboxes = await screen.findAllByRole("checkbox");
    fireEvent.click(checkboxes[1]);
    fireEvent.click(checkboxes[2]);
    fireEvent.click(screen.getByText("Export"));

    await waitFor(() => {
      expect(exportsApi.download).toHaveBeenCalledTimes(2);
      expect(exportsApi.download).toHaveBeenCalledWith("p1");
      expect(exportsApi.download).toHaveBeenCalledWith("p2");
    });
    expect(createObjectURL).toHaveBeenCalledTimes(2);
    expect(toast).toHaveBeenCalledWith(expect.objectContaining({ title: "Export complete" }));
    vi.unstubAllGlobals();
  });

  it("skips export for packets without a built final packet", async () => {
    (exportsApi.download as ReturnType<typeof vi.fn>).mockRejectedValue(new Error("not built"));
    vi.stubGlobal("URL", { ...URL, createObjectURL: vi.fn(), revokeObjectURL: vi.fn() });

    renderPage();
    const checkboxes = await screen.findAllByRole("checkbox");
    fireEvent.click(checkboxes[1]);
    fireEvent.click(screen.getByText("Export"));

    await waitFor(() => {
      expect(toast).toHaveBeenCalledWith(expect.objectContaining({ title: "Export skipped" }));
    });
    vi.unstubAllGlobals();
  });

  it("bulk deletes selected packets after confirmation", async () => {
    (packetsApi.delete as ReturnType<typeof vi.fn>).mockResolvedValue({});
    vi.spyOn(window, "confirm").mockReturnValue(true);

    renderPage();
    const checkboxes = await screen.findAllByRole("checkbox");
    fireEvent.click(checkboxes[1]);
    fireEvent.click(checkboxes[2]);
    fireEvent.click(screen.getByText("Delete"));

    await waitFor(() => {
      expect(packetsApi.delete).toHaveBeenCalledTimes(2);
      expect(packetsApi.delete).toHaveBeenCalledWith("p1");
      expect(packetsApi.delete).toHaveBeenCalledWith("p2");
    });
    expect(toast).toHaveBeenCalledWith(expect.objectContaining({ title: "Packets deleted" }));
    vi.restoreAllMocks();
  });

  it("filters packets by search query", async () => {
    renderPage();
    fireEvent.change(await screen.findByPlaceholderText("Search packets..."), {
      target: { value: "draft" },
    });
    expect(screen.queryByText("Smith v. Jones")).not.toBeInTheDocument();
    expect(screen.getByText("Draft Packet")).toBeInTheDocument();
  });
});
