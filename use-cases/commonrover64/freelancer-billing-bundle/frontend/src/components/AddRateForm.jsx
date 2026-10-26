import { useState } from "react";
import { createRateCard } from "../services/api.js";

const today = new Date().toISOString().slice(0, 10);

function AddRateForm({ clientId, onCreated }) {
    const [hourlyRate, setHourlyRate] = useState("");
    const [currency, setCurrency] = useState("INR");
    const [effectiveFrom, setEffectiveFrom] = useState("");
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);

    async function handleSubmit(e) {
        e.preventDefault();
        setLoading(true);
        setError(null);

        try {
            const rateCard = await createRateCard(clientId, {
                hourlyRate: Number(hourlyRate),
                currency,
                effectiveFrom,
            });

            setHourlyRate("");
            setEffectiveFrom("");

            onCreated(rateCard);
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    }

    return (
        <form onSubmit={handleSubmit} className="card">
            <h3>Add New Rate</h3>
            <p style={{ fontStyle: "italic" }}>
                Use this when a client's rate changes partway through an
                engagement.
            </p>

            <label>
                New hourly rate
                <input
                    type="number"
                    min="0.01"
                    step="0.01"
                    value={hourlyRate}
                    onChange={(e) => setHourlyRate(e.target.value)}
                    required
                />
            </label>
            <label>
                Currency
                <input
                    value={currency}
                    onChange={(e) => setCurrency(e.target.value.toUpperCase())}
                    pattern="[A-Z]{3}"
                    maxLength={3}
                    title="3-letter currency code, e.g. INR"
                    required
                />
            </label>
            <label>
                Effective from
                <input
                    type="date"
                    min={today}
                    value={effectiveFrom}
                    onChange={(e) => setEffectiveFrom(e.target.value)}
                    required
                />
            </label>

            {error && (
                <p style={{ color: "var(--coral)", fontWeight: 700 }}>
                    {error}
                </p>
            )}

            <button className="btn btn-coral" type="submit" disabled={loading}>
                {loading ? "Saving..." : "Add Rate"}
            </button>
        </form>
    );
}

export default AddRateForm;
