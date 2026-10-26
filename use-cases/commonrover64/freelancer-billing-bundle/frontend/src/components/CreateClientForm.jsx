import { useState } from "react";
import { createClient, createRateCard } from "../services/api.js";

const today = new Date().toISOString().slice(0, 10);

function CreateClientForm({ onCreated }) {
    const [name, setName] = useState("");
    const [email, setEmail] = useState("");
    const [phone, setPhone] = useState("");
    const [address, setAddress] = useState("");
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
            const client = await createClient({ name, email, phone, address });
            await createRateCard(client.id, {
                hourlyRate: Number(hourlyRate),
                currency,
                effectiveFrom,
            });

            setName("");
            setEmail("");
            setPhone("");
            setAddress("");
            setHourlyRate("");
            setEffectiveFrom("");

            onCreated(client);
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    }

    return (
        <form onSubmit={handleSubmit} className="card">
            <h3>New Client</h3>

            <label>
                Name
                <input
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    required
                />
            </label>
            <label>
                Email
                <input
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                />
            </label>
            <label>
                Phone
                <input
                    type="tel"
                    value={phone}
                    onChange={(e) => setPhone(e.target.value)}
                    pattern="[0-9]{7,15}"
                    title="7 to 15 digits, numbers only"
                />
            </label>
            <label>
                Address
                <input
                    value={address}
                    onChange={(e) => setAddress(e.target.value)}
                />
            </label>
            <label>
                Starting hourly rate
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
                Rate effective from
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
                {loading ? "Creating..." : "Create Client"}
            </button>
        </form>
    );
}

export default CreateClientForm;
