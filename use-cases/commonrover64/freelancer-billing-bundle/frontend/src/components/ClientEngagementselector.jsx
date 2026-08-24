import { useEffect, useState } from "react";
import { listClients, listEngagementsForClient } from "../services/api.js";

// let the user pick a client, then an engagement under that client.
// calls onSelect(engagementId) once both are chosen.
function ClientEngagementSelector({ onSelect }) {
    const [clients, setClients] = useState([]);
    const [selectedClientId, setSelectedClientId] = useState("");
    const [engagements, setEngagements] = useState([]);
    const [selectedEngagementId, setSelectedEngagementId] = useState("");
    const [error, setError] = useState(null);

    useEffect(() => {
        listClients()
            .then(setClients)
            .catch((err) => setError(err.message));
    }, []);

    useEffect(() => {
        if (!selectedClientId) {
            setEngagements([]);
            return;
        }
        listEngagementsForClient(selectedClientId)
            .then(setEngagements)
            .catch((err) => setError(err.message));
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
        <div
            style={{
                display: "flex",
                gap: "2rem",
                alignItems: "center",
                flexWrap: "wrap",
            }}
        >
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

            {selectedClientId && (
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
                            <option key={engagement.id} value={engagement.id}>
                                {engagement.title}
                            </option>
                        ))}
                    </select>
                </label>
            )}
        </div>
    );
}

export default ClientEngagementSelector;
