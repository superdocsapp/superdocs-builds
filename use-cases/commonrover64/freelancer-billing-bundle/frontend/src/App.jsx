import "./App.css"
import { useState } from "react";
import ClientSidebar from "./components/ClientSidebar.jsx";
import ClientDetailsPanel from "./components/ClientDetailsPanel.jsx";
import DocumentActionsPanel from "./components/DocumentActionsPanel.jsx";
import { useClientDirectory } from "./hooks/useClientDirectory.js";

function App() {
    const { clients } = useClientDirectory();
    const [selectedClientId, setSelectedClientId] = useState(null);
    const [selectedEngagementId, setSelectedEngagementId] = useState(null);
    const [selectedEngagementTitle, setSelectedEngagementTitle] =
        useState(null);

    const selectedClient = clients.find(
        (c) => String(c.id) === String(selectedClientId),
    );

    function handleSelectClient(clientId) {
        setSelectedClientId(clientId);
        setSelectedEngagementId(null);
        setSelectedEngagementTitle(null);
    }

    function handleSelectEngagement(engagementId, title) {
        setSelectedEngagementId(engagementId || null);
        setSelectedEngagementTitle(title || null);
    }

    return (
        <div style={{ padding: "2rem" }}>
            <h1>Freelancer Billing Bundle</h1>

            <div
                style={{
                    display: "flex",
                    gap: "1.5rem",
                    alignItems: "flex-start",
                }}
            >
                <ClientSidebar
                    selectedClientId={selectedClientId}
                    onSelectClient={handleSelectClient}
                />

                <ClientDetailsPanel
                    client={selectedClient}
                    selectedEngagementId={selectedEngagementId}
                    onSelectEngagement={(id) => handleSelectEngagement(id)}
                />

                <DocumentActionsPanel
                    engagementId={selectedEngagementId}
                    engagementTitle={selectedEngagementTitle}
                    clientName={selectedClient?.name}
                />
            </div>
        </div>
    );
}

export default App;
