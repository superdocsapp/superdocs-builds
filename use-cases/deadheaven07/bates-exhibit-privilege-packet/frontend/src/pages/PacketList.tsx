import { useState } from "react";
import { Link } from "react-router-dom";
import { Plus, FileText, Search, Trash2, Edit, Loader2, AlertCircle, Download, Layers, ShieldCheck, Info, ExternalLink, Hash, Sparkles } from "lucide-react";
import { usePackets, useDeletePacket, useUpdatePacket, useCreatePacket } from "@/hooks/usePackets";
import { exportsApi } from "@/services/exports";
import { toast } from "@/components/ui/use-toast";
import { Modal } from "@/components/ui/modal";
import { Drawer } from "@/components/ui/drawer";
import { Badge } from "@/components/ui/badge";
import type { Packet } from "@/types/api";

const getStatusBadgeVariant = (status: string): "success" | "indigo" | "default" | "danger" | "warning" => {
  switch (status) {
    case "completed":
      return "success";
    case "in_progress":
      return "indigo";
    case "failed":
      return "danger";
    case "assembling":
    case "waiting_review":
      return "warning";
    default:
      return "default";
  }
};

const formatDate = (dateStr: string) => {
  return new Date(dateStr).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
};

const MATTER_PRESETS = [
  { label: "Commercial Contract Breach", prefix: "CON-", desc: "Service agreements, invoices, email correspondence" },
  { label: "Medical & Health Records", prefix: "MED-", desc: "Diagnostic reports, treatment records, pharmacy bills" },
  { label: "Corporate Strategy & Audit", prefix: "CORP-", desc: "Board resolutions, strategy memos, financial audits" },
];

export function PacketList() {
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<"all" | "completed" | "in_progress">("all");
  const [selectedPackets, setSelectedPackets] = useState<string[]>([]);
  const [newPacketName, setNewPacketName] = useState("");
  const [newPacketDesc, setNewPacketDesc] = useState("");
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [editingPacket, setEditingPacket] = useState<Packet | null>(null);
  const [inspectingPacket, setInspectingPacket] = useState<Packet | null>(null);
  const [isExporting, setIsExporting] = useState(false);
  const [isDeletingBulk, setIsDeletingBulk] = useState(false);

  const { data: packets, isLoading, error, refetch } = usePackets();
  const deletePacket = useDeletePacket();
  const createPacket = useCreatePacket();
  const updatePacket = useUpdatePacket();

  const handleCreatePacket = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newPacketName.trim()) return;
    if (editingPacket) {
      await updatePacket.mutateAsync({
        id: editingPacket.id,
        data: {
          name: newPacketName.trim(),
        },
      });
      toast({ title: "Packet updated", description: `"${newPacketName.trim()}" saved.` });
    } else {
      await createPacket.mutateAsync({
        name: newPacketName.trim(),
      });
      toast({ title: "Packet created", description: `"${newPacketName.trim()}" created.` });
    }
    setNewPacketName("");
    setNewPacketDesc("");
    setEditingPacket(null);
    setShowCreateModal(false);
    refetch();
  };

  const openEditModal = (packet: Packet) => {
    setEditingPacket(packet);
    setNewPacketName(packet.name);
    setNewPacketDesc(packet.description || "");
    setShowCreateModal(true);
  };

  const handleBulkExport = async () => {
    setIsExporting(true);
    try {
      for (const id of selectedPackets) {
        try {
          const blob = await exportsApi.download(id);
          const url = URL.createObjectURL(blob);
          const a = document.createElement("a");
          a.href = url;
          a.download = `${packets?.find((p) => p.id === id)?.name ?? "packet"}.pdf`;
          a.click();
          URL.revokeObjectURL(url);
        } catch {
          toast({ title: "Export skipped", description: `Packet has no built final packet.`, variant: "destructive" });
        }
      }
      toast({ title: "Export complete", description: `${selectedPackets.length} packet(s) exported.` });
    } finally {
      setIsExporting(false);
    }
  };

  const handleBulkDelete = async () => {
    if (!window.confirm(`Delete ${selectedPackets.length} selected packet(s)? This cannot be undone.`)) return;
    setIsDeletingBulk(true);
    try {
      for (const id of selectedPackets) {
        await deletePacket.mutateAsync(id);
      }
      setSelectedPackets([]);
      toast({ title: "Packets deleted", description: `${selectedPackets.length} packet(s) removed.` });
      refetch();
    } finally {
      setIsDeletingBulk(false);
    }
  };

  const filteredPackets = (packets || []).filter((p) => {
    const matchesSearch =
      p.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (p.description && p.description.toLowerCase().includes(searchQuery.toLowerCase()));
    const matchesStatus =
      statusFilter === "all" ||
      (statusFilter === "completed" && p.status === "completed") ||
      (statusFilter === "in_progress" && p.status !== "completed");
    return matchesSearch && matchesStatus;
  });

  const totalPages = packets?.reduce((acc, p) => acc + (p.total_pages || 0), 0) || 0;
  const completedPackets = packets?.filter((p) => p.status === "completed").length || 0;
  const inProgressPackets = packets?.filter((p) => p.status !== "completed").length || 0;

  if (isLoading) {
    return (
      <div className="p-8 max-w-7xl mx-auto">
        <div className="flex flex-col items-center justify-center py-28 dark:bg-slate-900/60 bg-white/80 rounded-3xl border dark:border-slate-800/80 border-slate-200 backdrop-blur-xl shadow-2xl">
          <Loader2 className="h-10 w-10 animate-spin text-indigo-500" />
          <span className="mt-4 text-sm font-medium dark:text-slate-300 text-slate-600 font-display">Loading exhibit packets...</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-8 max-w-7xl mx-auto">
        <div className="dark:bg-rose-950/40 bg-rose-50 border dark:border-rose-800/80 border-rose-200 rounded-3xl p-6 backdrop-blur-md shadow-2xl">
          <div className="flex items-center gap-3">
            <AlertCircle className="h-6 w-6 text-rose-500" />
            <span className="text-base font-semibold dark:text-rose-200 text-rose-800">Failed to load packets</span>
          </div>
          <p className="text-sm dark:text-rose-300 text-rose-700 mt-2">{error.message}</p>
          <button 
            onClick={() => refetch()}
            className="mt-4 px-4 py-2 text-sm font-medium bg-rose-600 text-white rounded-xl hover:bg-rose-500 transition-colors shadow-lg shadow-rose-900/40"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8 animate-fade-in">
      {/* Top Header Banner */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-2 border-b dark:border-slate-800/80 border-slate-200/80">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-3xl font-display font-bold tracking-tight dark:text-white text-slate-900">Packets</h1>
            <Badge variant="indigo" size="md">
              {packets?.length || 0} Total
            </Badge>
          </div>
          <p className="dark:text-slate-400 text-slate-600 text-sm mt-1">Manage your Bates-stamped exhibit packets and evidence sets</p>
        </div>
        <button
          onClick={() => {
            setEditingPacket(null);
            setNewPacketName("");
            setNewPacketDesc("");
            setShowCreateModal(true);
          }}
          className="inline-flex items-center gap-2 px-5 py-2.5 bg-gradient-to-r from-indigo-500 via-sky-500 to-indigo-600 hover:from-indigo-400 hover:to-indigo-500 text-white font-semibold text-sm rounded-xl shadow-lg shadow-indigo-600/25 hover:shadow-indigo-500/40 transition-all duration-200 transform hover:-translate-y-0.5 cursor-pointer"
        >
          <Plus className="h-4 w-4" />
          New Packet
        </button>
      </div>

      {/* Analytics Metric Highlights */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="p-5 rounded-2xl dark:bg-slate-900/60 bg-white border dark:border-slate-800/80 border-slate-200/80 shadow-sm backdrop-blur-md flex items-center justify-between hover:border-sky-500/40 hover:shadow-md transition-all duration-200">
          <div>
            <p className="text-xs font-mono uppercase tracking-wider dark:text-slate-400 text-slate-500 font-medium">Total Cases</p>
            <p className="text-2xl font-display font-bold dark:text-white text-slate-900 mt-1">{packets?.length || 0} active</p>
            <p className="text-[11px] font-mono text-sky-500 mt-1 flex items-center gap-1">
              <span className="h-1.5 w-1.5 rounded-full bg-sky-500 animate-pulse" />
              Live Workspace Ready
            </p>
          </div>
          <div className="h-12 w-12 rounded-2xl dark:bg-sky-500/10 bg-sky-50 border dark:border-sky-500/20 border-sky-200 flex items-center justify-center text-sky-500 shadow-inner">
            <FileText className="h-6 w-6" />
          </div>
        </div>

        <div className="p-5 rounded-2xl dark:bg-slate-900/60 bg-white border dark:border-slate-800/80 border-slate-200/80 shadow-sm backdrop-blur-md flex items-center justify-between hover:border-indigo-500/40 hover:shadow-md transition-all duration-200">
          <div>
            <p className="text-xs font-mono uppercase tracking-wider dark:text-slate-400 text-slate-500 font-medium">Bates Stamped</p>
            <p className="text-2xl font-display font-bold dark:text-white text-slate-900 mt-1">{totalPages} pages total</p>
            <p className="text-[11px] font-mono text-indigo-500 mt-1">
              Contiguous Sequential Range
            </p>
          </div>
          <div className="h-12 w-12 rounded-2xl dark:bg-indigo-500/10 bg-indigo-50 border dark:border-indigo-500/20 border-indigo-200 flex items-center justify-center text-indigo-500 shadow-inner">
            <Layers className="h-6 w-6" />
          </div>
        </div>

        <div className="p-5 rounded-2xl dark:bg-slate-900/60 bg-white border dark:border-slate-800/80 border-slate-200/80 shadow-sm backdrop-blur-md flex items-center justify-between hover:border-emerald-500/40 hover:shadow-md transition-all duration-200">
          <div>
            <p className="text-xs font-mono uppercase tracking-wider dark:text-slate-400 text-slate-500 font-medium">Built & Verified</p>
            <p className="text-2xl font-display font-bold text-emerald-500 mt-1">{completedPackets} ready</p>
            <p className="text-[11px] font-mono text-emerald-500 mt-1">
              SHA-256 Ledger Verified
            </p>
          </div>
          <div className="h-12 w-12 rounded-2xl dark:bg-emerald-500/10 bg-emerald-50 border dark:border-emerald-500/20 border-emerald-200 flex items-center justify-center text-emerald-500 shadow-inner">
            <ShieldCheck className="h-6 w-6" />
          </div>
        </div>
      </div>

      {/* Create / Edit Modal Popup */}
      <Modal
        isOpen={showCreateModal}
        onClose={() => {
          setShowCreateModal(false);
          setEditingPacket(null);
          setNewPacketName("");
          setNewPacketDesc("");
        }}
        title={editingPacket ? "Edit Exhibit Packet" : "Create New Exhibit Packet"}
        description="Configure packet details and sequential Bates stamping properties."
        footer={
          <>
            <button
              type="button"
              onClick={() => {
                setShowCreateModal(false);
                setEditingPacket(null);
                setNewPacketName("");
                setNewPacketDesc("");
              }}
              className="px-4 py-2 text-sm font-medium dark:text-slate-400 text-slate-600 hover:text-slate-900 dark:hover:text-white dark:bg-slate-800/80 bg-slate-100 hover:bg-slate-200 dark:hover:bg-slate-800 rounded-xl transition-colors cursor-pointer"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleCreatePacket}
              disabled={createPacket.isPending || updatePacket.isPending || !newPacketName.trim()}
              className="px-5 py-2 text-sm font-semibold bg-gradient-to-r from-indigo-500 to-sky-500 hover:from-indigo-400 hover:to-sky-400 text-white rounded-xl shadow-lg shadow-indigo-600/25 disabled:opacity-50 transition-all flex items-center gap-2 cursor-pointer"
            >
              {(createPacket.isPending || updatePacket.isPending) ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Saving...
                </>
              ) : (
                editingPacket ? "Save Changes" : "Create Packet"
              )}
            </button>
          </>
        }
      >
        <form onSubmit={handleCreatePacket} className="space-y-4">
          <div>
            <label className="block text-xs font-mono uppercase tracking-wider dark:text-slate-300 text-slate-700 font-medium mb-1.5">Packet Name</label>
            <input
              type="text"
              value={newPacketName}
              onChange={(e) => setNewPacketName(e.target.value)}
              className="w-full px-4 py-2.5 dark:bg-slate-950 bg-white border dark:border-slate-700/80 border-slate-300 rounded-xl dark:text-white text-slate-900 dark:placeholder-slate-500 placeholder-slate-400 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
              placeholder="e.g., Smith v. Jones - Exhibits"
              autoFocus
            />
          </div>

          <div>
            <label className="block text-xs font-mono uppercase tracking-wider dark:text-slate-300 text-slate-700 font-medium mb-1.5">Description (Optional)</label>
            <input
              type="text"
              value={newPacketDesc}
              onChange={(e) => setNewPacketDesc(e.target.value)}
              className="w-full px-4 py-2.5 dark:bg-slate-950 bg-white border dark:border-slate-700/80 border-slate-300 rounded-xl dark:text-white text-slate-900 dark:placeholder-slate-500 placeholder-slate-400 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
              placeholder="e.g., Plaintiff evidentiary submission for hearing"
            />
          </div>

          {!editingPacket && (
            <div className="pt-2">
              <span className="block text-[11px] font-mono uppercase tracking-wider dark:text-slate-400 text-slate-500 font-medium mb-2">
                Quick Matter Presets
              </span>
              <div className="grid grid-cols-1 gap-2">
                {MATTER_PRESETS.map((preset) => (
                  <button
                    key={preset.label}
                    type="button"
                    onClick={() => {
                      setNewPacketName(`${preset.label} Bundle`);
                      setNewPacketDesc(preset.desc);
                    }}
                    className="p-2.5 text-left rounded-xl dark:bg-slate-900/60 bg-slate-50 hover:bg-sky-50 dark:hover:bg-slate-800/80 border dark:border-slate-800 border-slate-200 hover:border-sky-300 dark:hover:border-sky-500/40 transition-all flex items-center justify-between group cursor-pointer"
                  >
                    <div>
                      <span className="text-xs font-semibold dark:text-slate-200 text-slate-800 group-hover:text-sky-500 transition-colors">
                        {preset.label}
                      </span>
                      <p className="text-[11px] dark:text-slate-400 text-slate-500">{preset.desc}</p>
                    </div>
                    <Sparkles className="h-3.5 w-3.5 text-slate-400 group-hover:text-sky-500 transition-colors shrink-0" />
                  </button>
                ))}
              </div>
            </div>
          )}
        </form>
      </Modal>

      {/* Quick Packet Inspection Side Drawer */}
      <Drawer
        isOpen={!!inspectingPacket}
        onClose={() => setInspectingPacket(null)}
        title={
          <div className="flex items-center gap-2">
            <FileText className="h-5 w-5 text-indigo-500" />
            <span>{inspectingPacket?.name}</span>
          </div>
        }
        subtitle={`Packet ID: ${inspectingPacket?.id}`}
        footer={
          inspectingPacket && (
            <Link
              to={`/packets/${inspectingPacket.id}`}
              className="w-full py-2.5 px-4 bg-gradient-to-r from-indigo-500 to-sky-500 hover:from-indigo-400 hover:to-sky-400 text-white rounded-xl text-center font-semibold text-sm shadow-md shadow-indigo-600/30 flex items-center justify-center gap-2 transition-all"
            >
              Open Full Workspace
              <ExternalLink className="h-4 w-4" />
            </Link>
          )
        }
      >
        {inspectingPacket && (
          <div className="space-y-6">
            <div className="grid grid-cols-2 gap-3">
              <div className="p-4 dark:bg-slate-950/60 bg-slate-50 rounded-xl border dark:border-slate-800 border-slate-200">
                <span className="text-[11px] font-mono dark:text-slate-400 text-slate-500 uppercase">Status</span>
                <div className="mt-1">
                  <Badge variant={getStatusBadgeVariant(inspectingPacket.status || "draft")}>
                    {(inspectingPacket.status || "draft").replace("_", " ")}
                  </Badge>
                </div>
              </div>
              <div className="p-4 dark:bg-slate-950/60 bg-slate-50 rounded-xl border dark:border-slate-800 border-slate-200">
                <span className="text-[11px] font-mono dark:text-slate-400 text-slate-500 uppercase">Documents</span>
                <p className="text-lg font-bold dark:text-white text-slate-900 font-mono mt-0.5">
                  {inspectingPacket.document_count ?? 0} docs ({inspectingPacket.total_pages ?? 0} pgs)
                </p>
              </div>
            </div>

            <div className="p-4 dark:bg-slate-950/60 bg-slate-50 rounded-xl border dark:border-slate-800 border-slate-200 space-y-2">
              <div className="flex items-center gap-2 text-sky-500">
                <Hash className="h-4 w-4" />
                <span className="text-xs font-mono uppercase font-semibold">Bates Stamping Config</span>
              </div>
              <div className="grid grid-cols-3 gap-2 pt-2 text-xs font-mono">
                <div>
                  <span className="dark:text-slate-500 text-slate-400 block text-[10px]">Prefix</span>
                  <span className="dark:text-slate-200 text-slate-800 font-semibold">{inspectingPacket.bates_prefix || "CASE-"}</span>
                </div>
                <div>
                  <span className="dark:text-slate-500 text-slate-400 block text-[10px]">Start Number</span>
                  <span className="dark:text-slate-200 text-slate-800 font-semibold">{inspectingPacket.bates_start_number ?? 1}</span>
                </div>
                <div>
                  <span className="dark:text-slate-500 text-slate-400 block text-[10px]">Padding</span>
                  <span className="dark:text-slate-200 text-slate-800 font-semibold">{inspectingPacket.bates_padding ?? 6} digits</span>
                </div>
              </div>
            </div>

            {inspectingPacket.description && (
              <div className="p-4 dark:bg-slate-950/60 bg-slate-50 rounded-xl border dark:border-slate-800 border-slate-200">
                <span className="text-[11px] font-mono dark:text-slate-400 text-slate-500 uppercase">Description</span>
                <p className="text-sm dark:text-slate-300 text-slate-700 mt-1 leading-relaxed">{inspectingPacket.description}</p>
              </div>
            )}

            <div className="space-y-1 text-xs font-mono dark:text-slate-500 text-slate-400">
              <p>Created: {inspectingPacket.created_at ? formatDate(inspectingPacket.created_at) : "N/A"}</p>
              <p>Updated: {inspectingPacket.updated_at ? formatDate(inspectingPacket.updated_at) : "N/A"}</p>
            </div>
          </div>
        )}
      </Drawer>

      {/* Main Table Container */}
      <div className="dark:bg-slate-900/70 bg-white border dark:border-slate-800/80 border-slate-200/90 rounded-2xl overflow-hidden backdrop-blur-md shadow-sm">
        {/* Search & Filter Toolbar */}
        <div className="p-4 border-b dark:border-slate-800/80 border-slate-200/80 dark:bg-slate-950/30 bg-slate-50/50 flex flex-col md:flex-row gap-4 items-center justify-between">
          <div className="relative flex-1 max-w-md w-full">
            <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 dark:text-slate-400 text-slate-500" />
            <input
              type="text"
              placeholder="Search packets..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-10 pr-4 py-2 dark:bg-slate-950/80 bg-white border dark:border-slate-700/70 border-slate-300 rounded-xl dark:text-slate-100 text-slate-900 dark:placeholder-slate-500 placeholder-slate-400 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
            />
          </div>

          {/* Status Filter Chips */}
          <div className="flex items-center gap-1.5 self-start md:self-auto">
            <button
              onClick={() => setStatusFilter("all")}
              className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-all cursor-pointer ${
                statusFilter === "all"
                  ? "dark:bg-sky-500/20 dark:text-sky-300 bg-sky-100 text-sky-700 border dark:border-sky-500/40 border-sky-300 shadow-sm"
                  : "dark:text-slate-400 text-slate-600 hover:bg-slate-100 dark:hover:bg-slate-800"
              }`}
            >
              All ({packets?.length || 0})
            </button>
            <button
              onClick={() => setStatusFilter("completed")}
              className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-all cursor-pointer ${
                statusFilter === "completed"
                  ? "dark:bg-emerald-500/20 dark:text-emerald-300 bg-emerald-100 text-emerald-700 border dark:border-emerald-500/40 border-emerald-300 shadow-sm"
                  : "dark:text-slate-400 text-slate-600 hover:bg-slate-100 dark:hover:bg-slate-800"
              }`}
            >
              Verified ({completedPackets})
            </button>
            <button
              onClick={() => setStatusFilter("in_progress")}
              className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-all cursor-pointer ${
                statusFilter === "in_progress"
                  ? "dark:bg-indigo-500/20 dark:text-indigo-300 bg-indigo-100 text-indigo-700 border dark:border-indigo-500/40 border-indigo-300 shadow-sm"
                  : "dark:text-slate-400 text-slate-600 hover:bg-slate-100 dark:hover:bg-slate-800"
              }`}
            >
              In Progress ({inProgressPackets})
            </button>
          </div>
        </div>

        {/* Table Content */}
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead className="dark:bg-slate-950/50 bg-slate-50 border-b dark:border-slate-800 border-slate-200 text-[11px] font-mono uppercase tracking-wider dark:text-slate-400 text-slate-600">
              <tr>
                <th className="px-5 py-3.5 w-12">
                  <input
                    type="checkbox"
                    className="h-4 w-4 rounded dark:border-slate-700 border-slate-300 dark:bg-slate-900 bg-white text-indigo-600 focus:ring-indigo-500 cursor-pointer"
                    checked={selectedPackets.length === filteredPackets.length && filteredPackets.length > 0}
                    onChange={(e) =>
                      setSelectedPackets(
                        e.target.checked ? filteredPackets.map((p) => p.id) : []
                      )
                    }
                  />
                </th>
                <th className="px-5 py-3.5">Packet</th>
                <th className="px-5 py-3.5">Documents</th>
                <th className="px-5 py-3.5">Pages</th>
                <th className="px-5 py-3.5">Status</th>
                <th className="px-5 py-3.5">Updated</th>
                <th className="px-5 py-3.5 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y dark:divide-slate-800/60 divide-slate-200 text-sm">
              {filteredPackets.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-5 py-16 text-center dark:text-slate-400 text-slate-500">
                    <Layers className="h-10 w-10 mx-auto dark:text-slate-500 text-slate-400 mb-3" />
                    <p className="dark:text-slate-300 text-slate-700 font-medium font-display">No packets found</p>
                    <p className="text-xs dark:text-slate-400 text-slate-500 mt-1">Create your first packet to get started.</p>
                  </td>
                </tr>
              ) : (
                filteredPackets.map((packet) => (
                  <tr
                    key={packet.id}
                    className="dark:hover:bg-slate-800/40 hover:bg-slate-50/80 transition-colors group cursor-pointer"
                  >
                    <td className="px-5 py-4" onClick={(e) => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        className="h-4 w-4 rounded dark:border-slate-700 border-slate-300 dark:bg-slate-900 bg-white text-indigo-600 focus:ring-indigo-500 cursor-pointer"
                        checked={selectedPackets.includes(packet.id)}
                        onChange={(e) =>
                          setSelectedPackets((prev) =>
                            e.target.checked
                              ? [...prev, packet.id]
                              : prev.filter((id) => id !== packet.id)
                          )
                        }
                      />
                    </td>
                    <td className="px-5 py-4">
                      <Link
                        to={`/packets/${packet.id}`}
                        className="font-semibold dark:text-white text-slate-900 group-hover:text-sky-500 transition-colors flex items-center gap-2"
                      >
                        <span>{packet.name}</span>
                        {packet.bates_prefix && (
                          <span className="text-[10px] font-mono px-1.5 py-0.5 rounded dark:bg-slate-800 dark:text-slate-400 dark:border-slate-700 bg-slate-100 text-slate-600 border border-slate-200">
                            {packet.bates_prefix}
                          </span>
                        )}
                      </Link>
                      {packet.description && (
                        <p className="text-xs dark:text-slate-400 text-slate-500 mt-1 max-w-md line-clamp-1">{packet.description}</p>
                      )}
                    </td>
                    <td className="px-5 py-4 font-mono dark:text-slate-300 text-slate-700">{packet.document_count ?? 0}</td>
                    <td className="px-5 py-4 font-mono dark:text-slate-300 text-slate-700">{packet.total_pages ?? 0}</td>
                    <td className="px-5 py-4">
                      <Badge variant={getStatusBadgeVariant(packet.status || "draft")}>
                        {(packet.status || "draft").replace("_", " ")}
                      </Badge>
                    </td>
                    <td className="px-5 py-4 dark:text-slate-400 text-slate-500 text-xs font-mono">
                      {packet.updated_at ? formatDate(packet.updated_at) : "N/A"}
                    </td>
                    <td className="px-5 py-4 text-right" onClick={(e) => e.stopPropagation()}>
                      <div className="flex items-center justify-end gap-1.5">
                        <button
                          onClick={() => setInspectingPacket(packet)}
                          className="p-2 dark:text-slate-400 text-slate-500 hover:text-indigo-500 dark:hover:bg-slate-800 hover:bg-slate-100 rounded-lg transition-colors cursor-pointer"
                          title="Inspect Packet"
                        >
                          <Info className="h-4 w-4" />
                        </button>
                        <Link
                          to={`/packets/${packet.id}`}
                          className="p-2 dark:text-slate-400 text-slate-500 hover:text-sky-500 dark:hover:bg-slate-800 hover:bg-slate-100 rounded-lg transition-colors"
                          title="Open in Workspace"
                        >
                          <FileText className="h-4 w-4" />
                        </Link>
                        <button
                          onClick={() => openEditModal(packet)}
                          className="p-2 dark:text-slate-400 text-slate-500 hover:text-slate-900 dark:hover:text-slate-200 dark:hover:bg-slate-800 hover:bg-slate-100 rounded-lg transition-colors cursor-pointer"
                          title="Edit"
                        >
                          <Edit className="h-4 w-4" />
                        </button>
                        <button
                          onClick={() => {
                            deletePacket.mutate(packet.id);
                            setSelectedPackets((prev) => prev.filter((id) => id !== packet.id));
                          }}
                          disabled={deletePacket.isPending}
                          className="p-2 dark:text-slate-400 text-slate-500 hover:text-rose-500 hover:bg-rose-50 rounded-lg transition-colors disabled:opacity-50 cursor-pointer"
                          title="Delete packet"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Bulk Action Floating Drawer */}
        {selectedPackets.length > 0 && (
          <div className="p-4 border-t dark:border-slate-800 border-slate-200 dark:bg-slate-950/80 bg-slate-50 flex items-center justify-between animate-slide-up">
            <span className="text-xs font-mono dark:text-slate-300 text-slate-700">
              <span className="text-sky-500 font-bold">{selectedPackets.length}</span> packet(s) selected
            </span>
            <div className="flex gap-2.5">
              <button
                onClick={handleBulkExport}
                disabled={isExporting}
                className="px-3.5 py-1.5 text-xs font-medium dark:bg-slate-800 dark:hover:bg-slate-700 dark:text-white bg-white hover:bg-slate-100 text-slate-800 rounded-lg border dark:border-slate-700 border-slate-300 disabled:opacity-50 inline-flex items-center gap-1.5 transition-colors shadow-sm cursor-pointer"
              >
                {isExporting ? <Loader2 className="h-3.5 w-3.5 animate-spin text-sky-500" /> : <Download className="h-3.5 w-3.5" />}
                Export
              </button>
              <button
                onClick={handleBulkDelete}
                disabled={isDeletingBulk}
                className="px-3.5 py-1.5 text-xs font-medium dark:bg-rose-950/40 dark:border-rose-800 dark:text-rose-300 bg-rose-50 border border-rose-300 text-rose-700 hover:bg-rose-100 rounded-lg disabled:opacity-50 transition-colors cursor-pointer"
              >
                {isDeletingBulk ? "Deleting..." : "Delete"}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}