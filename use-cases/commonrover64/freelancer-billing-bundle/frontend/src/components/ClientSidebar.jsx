import { useState } from "react";
import { useClientDirectory } from "../hooks/useClientDirectory.js";
import CreateClientForm from "./CreateClientForm.jsx";
import DocumentModal from "./DocumentModal.jsx";

function ClientSidebar({ selectedClientId, onSelectClient }) {
    const {
        pagedClients,
        searchTerm,
        setSearchTerm,
        page,
        setPage,
        totalPages,
        error,
        refreshClients,
    } = useClientDirectory();

    const [showNewClient, setShowNewClient] = useState(false);

    return (
        <div className="card sidebar">
            <button
                className="btn btn-coral"
                style={{ width: "100%" }}
                onClick={() => setShowNewClient(true)}
            >
                + New Client
            </button>

            {showNewClient && (
                <DocumentModal
                    title="New Client"
                    onClose={() => setShowNewClient(false)}
                >
                    <CreateClientForm
                        onCreated={async (client) => {
                            await refreshClients();
                            onSelectClient(client.id);
                            setShowNewClient(false);
                        }}
                    />
                </DocumentModal>
            )}

            <input
                type="text"
                placeholder="Search clients..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="sidebar-search"
            />

            {error && (
                <p style={{ color: "var(--coral)", fontWeight: 700 }}>
                    {error}
                </p>
            )}

            <div className="sidebar-list">
                {pagedClients.map((client) => (
                    <button
                        key={client.id}
                        className={`sidebar-item ${String(client.id) === String(selectedClientId) ? "sidebar-item-active" : ""}`}
                        onClick={() => onSelectClient(client.id)}
                    >
                        <div style={{ fontWeight: 700 }}>{client.name}</div>
                        {client.email && (
                            <div style={{ fontSize: "0.85rem" }}>
                                {client.email}
                            </div>
                        )}
                    </button>
                ))}
                {pagedClients.length === 0 && (
                    <p style={{ fontStyle: "italic" }}>No clients found.</p>
                )}
            </div>

            <div className="sidebar-pagination">
                <button
                    className="btn"
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                    disabled={page <= 1}
                >
                    {"<"}
                </button>
                <span style={{ fontWeight: 700 }}>
                    {page} / {totalPages}
                </span>
                <button
                    className="btn"
                    onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                    disabled={page >= totalPages}
                >
                    {">"}
                </button>
            </div>
        </div>
    );
}

export default ClientSidebar;
