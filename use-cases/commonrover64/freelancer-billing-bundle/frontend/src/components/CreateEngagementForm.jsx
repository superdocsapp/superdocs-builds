import { useState } from "react";
import { createEngagement } from "../services/api.js";

const today = new Date().toISOString().slice(0, 10);

function CreateEngagementForm({ clientId, onCreated }) {
    const [title, setTitle] = useState("");
    const [startDate, setStartDate] = useState("");
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);

    async function handleSubmit(e) {
        e.preventDefault();
        setLoading(true);
        setError(null);

        try {
            const engagement = await createEngagement({
                clientId,
                title,
                startDate,
            });

            setTitle("");
            setStartDate("");

            onCreated(engagement);
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    }

    return (
        <form onSubmit={handleSubmit} className="card">
            <h3>New Engagement</h3>

            <label>
                Title
                <input
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    required
                />
            </label>
            <label>
                Start date
                <input
                    type="date"
                    min={today}
                    value={startDate}
                    onChange={(e) => setStartDate(e.target.value)}
                    required
                />
            </label>

            {error && (
                <p style={{ color: "var(--coral)", fontWeight: 700 }}>
                    {error}
                </p>
            )}

            <button className="btn btn-coral" type="submit" disabled={loading}>
                {loading ? "Creating..." : "Create Engagement"}
            </button>
        </form>
    );
}

export default CreateEngagementForm;
