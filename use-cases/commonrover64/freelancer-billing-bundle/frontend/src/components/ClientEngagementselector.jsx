import { useEffect, useState } from "react";
import { listClients, listEngagementsForClient } from "../services/api.js";
import CreateClientForm from "./CreateClientForm.jsx";
import CreateEngagementForm from "./CreateEngagementForm.jsx";
import AddRateForm from "./AddRateForm.jsx";
import LogTimesheetEntryForm from "./LogTimesheetEntryForm.jsx";

function ClientEngagementSelector({ onSelect }) {
    const [clients, setClients] = useState([]);
    const [selectedClientId, setSelectedClientId] = useState("");
    const [engagements, setEngagements] = useState([]);
    const [selectedEngagementId, setSelectedEngagementId] = useState("");
    const [error, setError] = useState(null);

    const [showNewClient, setShowNewClient] = useState(false);
    const [showNewEngagement, setShowNewEngagement] = useState(false);
    const [showAddRate, setShowAddRate] = useState(false);
    const [showLogHours, setShowLogHours] = useState(false);

    function refreshClients() {
        return listClients()
            .then(setClients)
            .catch((err) => setError(err.message));
    }

    function refreshEngagements(clientId) {
        return listEngagementsForClient(clientId)
            .then(setEngagements)
            .catch((err) => setError(err.message));
    }

    useEffect(() => {
        refreshClients();
    }, []);

    useEffect(() => {
        if (!selectedClientId) {
            setEngagements([]);
            return;
        }
        refreshEngagements(selectedClientId);
    }, [selectedClientId]);

    useEffect(() => {
        if (selectedEngagementId) {
            const engagement = engagements.find(
                (e) => String(e.id) === String(selectedEngagementId),
            );
            const client = clients.find(
                (c) => String(c.id) === String(selectedClientId),
            );
            onSelect({
                engagementId: selectedEngagementId,
                engagementTitle: engagement?.title,
                clientName: client?.name,
            });
        }
    }, [
        selectedEngagementId,
        engagements,
        clients,
        selectedClientId,
        onSelect,
    ]);

    if (error) {
        return <p style={{ color: "red" }}>Error: {error}</p>;
    }

    return (
        <div>
            <div className="selector-row">
                <label
                    style={{
                        display: "flex",
                        alignItems: "center",
                        gap: "0.6rem",
                        fontWeight: 700,
                    }}
                >
                    Client:
                    <select
                        value={selectedClientId}
                        onChange={(e) => {
                            setSelectedClientId(e.target.value);
                            setSelectedEngagementId("");
                        }}
                    >
                        <option value="">Select a client</option>
                        {clients.map((client) => (
                            <option key={client.id} value={client.id}>
                                {client.name}
                            </option>
                        ))}
                    </select>
                </label>

                <button
                    className="btn"
                    onClick={() => setShowNewClient((v) => !v)}
                >
                    {showNewClient ? "Cancel" : "+ New Client"}
                </button>

                {selectedClientId && (
                    <button
                        className="btn"
                        onClick={() => setShowAddRate((v) => !v)}
                    >
                        {showAddRate ? "Cancel" : "+ Add Rate"}
                    </button>
                )}
            </div>

            {selectedClientId && (
                <div className="selector-row">
                    <label
                        style={{
                            display: "flex",
                            alignItems: "center",
                            gap: "0.6rem",
                            fontWeight: 700,
                        }}
                    >
                        Engagement:
                        <select
                            value={selectedEngagementId}
                            onChange={(e) =>
                                setSelectedEngagementId(e.target.value)
                            }
                        >
                            <option value="">Select an engagement</option>
                            {engagements.map((engagement) => (
                                <option
                                    key={engagement.id}
                                    value={engagement.id}
                                >
                                    {engagement.title}
                                </option>
                            ))}
                        </select>
                    </label>

                    <button
                        className="btn"
                        onClick={() => setShowNewEngagement((v) => !v)}
                    >
                        {showNewEngagement ? "Cancel" : "+ New Engagement"}
                    </button>

                    {selectedEngagementId && (
                        <button
                            className="btn"
                            onClick={() => setShowLogHours((v) => !v)}
                        >
                            {showLogHours ? "Cancel" : "+ Log Hours"}
                        </button>
                    )}
                </div>
            )}

            {showNewClient && (
                <CreateClientForm
                    onCreated={async (client) => {
                        await refreshClients();
                        setSelectedClientId(client.id);
                        setShowNewClient(false);
                    }}
                />
            )}

            {showAddRate && selectedClientId && (
                <AddRateForm
                    clientId={selectedClientId}
                    onCreated={() => setShowAddRate(false)}
                />
            )}

            {showNewEngagement && selectedClientId && (
                <CreateEngagementForm
                    clientId={selectedClientId}
                    onCreated={async (engagement) => {
                        await refreshEngagements(selectedClientId);
                        setSelectedEngagementId(engagement.id);
                        setShowNewEngagement(false);
                    }}
                />
            )}

            {showLogHours && selectedEngagementId && (
                <LogTimesheetEntryForm
                    key={selectedEngagementId}
                    engagementId={selectedEngagementId}
                    minDate={
                        engagements.find(
                            (e) =>
                                String(e.id) === String(selectedEngagementId),
                        )?.start_date
                    }
                    onCreated={() => setShowLogHours(false)}
                />
            )}
        </div>
    );
}

export default ClientEngagementSelector;







//  GIT PUSH the ui changes or redesign the ui