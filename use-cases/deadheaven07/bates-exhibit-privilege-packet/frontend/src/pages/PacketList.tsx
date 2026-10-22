import { useState } from "react";
import { Link } from "react-router-dom";
import { Plus, FileText, Search, Filter, Trash2, Edit, Loader2, AlertCircle, Download } from "lucide-react";
import { clsx } from "clsx";
import { usePackets, useDeletePacket, useUpdatePacket } from "@/hooks/usePackets";
import { useCreatePacket } from "@/hooks/usePackets";
import { exportsApi } from "@/services/exports";
import { toast } from "@/components/ui/use-toast";
import type { Packet } from "@/types/api";

const getStatusBadge = (status: string) => {
  const styles = {
    completed: "bg-green-100 text-green-700",
    in_progress: "bg-blue-100 text-blue-700",
    draft: "bg-gray-100 text-gray-700",
    failed: "bg-red-100 text-red-700",
  };
  return styles[status as keyof typeof styles] || styles.draft;
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

export function PacketList() {
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedPackets, setSelectedPackets] = useState<string[]>([]);
  const [newPacketName, setNewPacketName] = useState("");
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [editingPacket, setEditingPacket] = useState<Packet | null>(null);
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
      await updatePacket.mutateAsync({ id: editingPacket.id, data: { name: newPacketName.trim() } });
      toast({ title: "Packet updated", description: `"${newPacketName.trim()}" saved.` });
    } else {
      await createPacket.mutateAsync({ name: newPacketName.trim() });
      toast({ title: "Packet created", description: `"${newPacketName.trim()}" created.` });
    }
    setNewPacketName("");
    setEditingPacket(null);
    setShowCreateModal(false);
    refetch();
  };

  const openEditModal = (packet: Packet) => {
    setEditingPacket(packet);
    setNewPacketName(packet.name);
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

  const filteredPackets = packets?.filter(
    (p) =>
      p.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      p.description?.toLowerCase().includes(searchQuery.toLowerCase())
  ) || [];

  if (isLoading) {
    return (
      <div className="p-6">
        <div className="flex items-center justify-center py-12">
          <Loader2 className="h-8 w-8 animate-spin text-primary-600" />
          <span className="ml-3 text-gray-600">Loading packets...</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6">
        <div className="bg-red-50 border border-red-200 rounded-lg p-4">
          <div className="flex items-center gap-2">
            <AlertCircle className="h-5 w-5 text-red-600" />
            <span className="text-red-800">Failed to load packets</span>
          </div>
          <p className="text-sm text-red-600 mt-2">{error.message}</p>
          <button 
            onClick={() => refetch()}
            className="mt-3 px-3 py-1.5 text-sm bg-red-600 text-white rounded-lg hover:bg-red-700"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Packets</h1>
          <p className="text-gray-500 mt-1">Manage your Bates-stamped exhibit packets</p>
        </div>
        <button
          onClick={() => setShowCreateModal(true)}
          className="inline-flex items-center gap-2 px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 transition-colors"
        >
          <Plus className="h-5 w-5" />
          New Packet
        </button>
      </div>

      {showCreateModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-white rounded-lg p-6 w-full max-w-md mx-4">
            <h2 className="text-xl font-bold mb-4">{editingPacket ? "Edit Packet" : "Create New Packet"}</h2>
            <form onSubmit={handleCreatePacket}>
              <div className="mb-4">
                <label className="block text-sm font-medium text-gray-700 mb-1">Packet Name</label>
                <input
                  type="text"
                  value={newPacketName}
                  onChange={(e) => setNewPacketName(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
                  placeholder="e.g., Smith v. Jones - Exhibits"
                  autoFocus
                />
              </div>
              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => {
                    setShowCreateModal(false);
                    setEditingPacket(null);
                    setNewPacketName("");
                  }}
                  className="px-4 py-2 text-sm border border-gray-300 rounded-lg hover:bg-gray-100"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={createPacket.isPending || updatePacket.isPending}
                  className="px-4 py-2 text-sm bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50"
                >
                  {(createPacket.isPending || updatePacket.isPending) ? (
                    <span className="flex items-center gap-2">
                      <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none"/><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"/></svg>
                      Saving...
                    </span>
                  ) : (
                    editingPacket ? 'Save Changes' : 'Create Packet'
                  )}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
        <div className="p-4 border-b border-gray-200">
          <div className="flex flex-col sm:flex-row gap-4">
            <div className="relative flex-1 max-w-md">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-5 w-5 text-gray-400" />
              <input
                type="text"
                placeholder="Search packets..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full pl-10 pr-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
              />
            </div>
            <Filter className="h-5 w-5 text-gray-400 mt-2 sm:mt-0" />
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  <input
                    type="checkbox"
                    className="h-4 w-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                    checked={selectedPackets.length === filteredPackets.length && filteredPackets.length > 0}
                    onChange={(e) =>
                      setSelectedPackets(
                        e.target.checked ? filteredPackets.map((p) => p.id) : []
                      )
                    }
                  />
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Packet
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Documents
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Pages
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Status
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Updated
                </th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {filteredPackets.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-12 text-center text-gray-500">
                    No packets found. Create your first packet to get started.
                  </td>
                </tr>
              ) : (
                filteredPackets.map((packet) => (
                  <tr
                    key={packet.id}
                    className="hover:bg-gray-50 transition-colors"
                  >
                    <td className="px-4 py-4">
                      <input
                        type="checkbox"
                        className="h-4 w-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
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
                    <td className="px-4 py-4">
                      <Link
                        to={`/packets/${packet.id}`}
                        className="font-medium text-gray-900 hover:text-primary-600"
                      >
                        {packet.name}
                      </Link>
                      {packet.description && (
                        <p className="text-sm text-gray-500 mt-1">{packet.description}</p>
                      )}
                    </td>
                    <td className="px-4 py-4 text-gray-600">{packet.document_count ?? 0}</td>
                    <td className="px-4 py-4 text-gray-600">{packet.total_pages ?? 0}</td>
                    <td className="px-4 py-4">
                      <span
                        className={clsx(
                          "inline-flex px-2 py-1 text-xs font-medium rounded-full",
                          getStatusBadge(packet.status || 'draft')
                        )}
                      >
                        {(packet.status || 'draft').replace("_", " ")}
                      </span>
                    </td>
                    <td className="px-4 py-4 text-gray-500 text-sm">
                      {packet.updated_at ? formatDate(packet.updated_at) : 'N/A'}
                    </td>
                    <td className="px-4 py-4 text-right">
                      <div className="flex items-center justify-end gap-1">
                        <Link
                          to={`/packets/${packet.id}`}
                          className="p-2 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
                          title="Open"
                        >
                          <FileText className="h-4 w-4" />
                        </Link>
                        <button
                          onClick={() => openEditModal(packet)}
                          className="p-2 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
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
                          className="p-2 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors disabled:opacity-50"
                          title="Delete"
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

        {selectedPackets.length > 0 && (
          <div className="p-4 border-t border-gray-200 bg-gray-50 flex items-center justify-between">
            <span className="text-sm text-gray-600">
              {selectedPackets.length} packet(s) selected
            </span>
            <div className="flex gap-2">
              <button
                onClick={handleBulkExport}
                disabled={isExporting}
                className="px-3 py-1.5 text-sm border border-gray-300 rounded-lg hover:bg-gray-100 disabled:opacity-50 inline-flex items-center gap-1.5"
              >
                {isExporting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}
                Export
              </button>
              <button
                onClick={handleBulkDelete}
                disabled={isDeletingBulk}
                className="px-3 py-1.5 text-sm border border-gray-300 rounded-lg hover:bg-red-50 hover:text-red-600 disabled:opacity-50"
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