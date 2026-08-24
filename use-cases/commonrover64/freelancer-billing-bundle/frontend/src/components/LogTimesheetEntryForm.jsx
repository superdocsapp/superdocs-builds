import { useState } from "react";
import { createTimesheetEntry } from "../services/api.js";

const today = new Date().toISOString().slice(0, 10);

function LogTimesheetEntryForm({ engagementId, minDate, onCreated }) {
    const [entryDate, setEntryDate] = useState("");
    const [hours, setHours] = useState("");
    const [description, setDescription] = useState("");
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);

    async function handleSubmit(e) {
        e.preventDefault();
        setLoading(true);
        setError(null);

        try {
            const entry = await createTimesheetEntry(engagementId, {
                entryDate,
                hours: Number(hours),
                description,
            });

            setEntryDate("");
            setHours("");
            setDescription("");

            onCreated(entry);
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    }

    return (
        <form onSubmit={handleSubmit} className="card">
            <h3>Log Hours</h3>

            <label>
                Date
                <input
                    type="date"
                    min={minDate}
                    max={today}
                    value={entryDate}
                    onChange={(e) => setEntryDate(e.target.value)}
                    required
                />
            </label>
            <label>
                Hours
                <input
                    type="number"
                    min="0.5"
                    max="24"
                    step="0.5"
                    value={hours}
                    onChange={(e) => setHours(e.target.value)}
                    required
                />
            </label>
            <label>
                Description
                <input
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                />
            </label>

            {error && (
                <p style={{ color: "var(--coral)", fontWeight: 700 }}>
                    {error}
                </p>
            )}

            <button className="btn btn-teal" type="submit" disabled={loading}>
                {loading ? "Logging..." : "Log Hours"}
            </button>
        </form>
    );
}

export default LogTimesheetEntryForm;
