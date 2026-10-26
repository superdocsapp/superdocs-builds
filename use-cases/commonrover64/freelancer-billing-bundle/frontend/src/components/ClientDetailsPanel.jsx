import { useEffect, useState } from "react";
import {
    listEngagementsForClient,
    listRateCardsForClient,
    getInvoiceForEngagement,
} from "../services/api.js";
import CreateEngagementForm from "./CreateEngagementForm.jsx";
import AddRateForm from "./AddRateForm.jsx";
import LogTimesheetEntryForm from "./LogTimesheetEntryForm.jsx";

function ClientDetailsPanel({
    client,
    selectedEngagementId,
    onSelectEngagement,
}) {
    const [engagements, setEngagements] = useState([]);
    const [rates, setRates] = useState([]);
    const [invoice, setInvoice] = useState(null);
    const [error, setError] = useState(null);

    const [showNewEngagement, setShowNewEngagement] = useState(false);
    const [showAddRate, setShowAddRate] = useState(false);
    const [showLogHours, setShowLogHours] = useState(false);

    function refreshEngagements() {
        return listEngagementsForClient(client.id)
            .then(setEngagements)
            .catch((err) => setError(err.message));
    }

    function refreshRates() {
        return listRateCardsForClient(client.id)
            .then(setRates)
            .catch((err) => setError(err.message));
    }

    function refreshInvoice() {
        if (!selectedEngagementId) {
            setInvoice(null);
            return;
        }
        getInvoiceForEngagement(selectedEngagementId)
            .then((data) => setInvoice(data.invoice))
            .catch((err) => setError(err.message));
    }

    useEffect(() => {
        if (!client) return;
        refreshEngagements();
        refreshRates();
    }, [client]);

    useEffect(() => {
        refreshInvoice();
    }, [selectedEngagementId]);

    if (!client) {
        return (
            <div className="card" style={{ flex: 1 }}>
                <h2>Welcome to the Freelancer Billing Bundle</h2>
                <p>
                    Manage clients, rates, and timesheets, then generate an
                    engagement letter, timesheet, invoice, or payment reminder,
                    reviewed and approved by you before anything gets committed.
                </p>
                <p style={{ fontStyle: "italic" }}>
                    Select a client to see details.
                </p>
            </div>
        );
    }

    const selectedEngagement = engagements.find(
        (e) => String(e.id) === String(selectedEngagementId),
    );
    // rates come back oldest-first, so the last one is the current rate.
    const currentRate = rates.length > 0 ? rates[rates.length - 1] : null;

    // flatten invoice line items into per-entry rows for the logged hours table.
    const loggedRows = invoice
        ? invoice.lineItems.flatMap((item) =>
              item.entries.map((entry) => ({
                  date: entry.date,
                  description: entry.description,
                  hours: entry.hours,
                  rate: item.hourlyRate,
                  amount: entry.hours * item.hourlyRate,
              })),
          )
        : [];

    return (
        <div className="card" style={{ flex: 1 }}>
            <h2>{client.name}</h2>
            <p>
                {client.email} {client.phone && `| ${client.phone}`}{" "}
                {client.address && `| ${client.address}`}
            </p>

            {error && (
                <p style={{ color: "var(--coral)", fontWeight: 700 }}>
                    {error}
                </p>
            )}

            <hr />

            <div className="selector-row">
                <h3 style={{ margin: 0 }}>Engagement</h3>
                <select
                    value={selectedEngagementId || ""}
                    onChange={(e) => {
                        const eng = engagements.find(
                            (x) => String(x.id) === e.target.value,
                        );
                        onSelectEngagement(e.target.value, eng?.title);
                    }}
                >
                    <option value="">Select an engagement</option>
                    {engagements.map((eng) => (
                        <option key={eng.id} value={eng.id}>
                            {eng.title}
                        </option>
                    ))}
                </select>
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

            {showNewEngagement && (
                <CreateEngagementForm
                    clientId={client.id}
                    onCreated={async (engagement) => {
                        await refreshEngagements();
                        onSelectEngagement(engagement.id, engagement.title);
                        setShowNewEngagement(false);
                    }}
                />
            )}

            <hr />

            <div className="selector-row">
                <h3 style={{ margin: 0 }}>Rate</h3>
                <button
                    className="btn"
                    onClick={() => setShowAddRate((v) => !v)}
                >
                    {showAddRate ? "Cancel" : "+ New Rate"}
                </button>
            </div>

            {showAddRate && (
                <AddRateForm
                    clientId={client.id}
                    onCreated={async () => {
                        await refreshRates();
                        setShowAddRate(false);
                    }}
                />
            )}

            {currentRate ? (
                <p>
                    <strong>
                        {currentRate.hourly_rate} {currentRate.currency}/hr
                    </strong>
                    , effective from {currentRate.effective_from}
                </p>
            ) : (
                <p style={{ fontStyle: "italic" }}>No rate set yet.</p>
            )}

            {showLogHours && selectedEngagementId && (
                <LogTimesheetEntryForm
                    key={selectedEngagementId}
                    engagementId={selectedEngagementId}
                    minDate={selectedEngagement?.start_date}
                    onCreated={async () => {
                        await refreshInvoice();
                        setShowLogHours(false);
                    }}
                />
            )}

            {selectedEngagementId && (
                <>
                    <hr />
                    <h3>Logged Hours</h3>
                    {loggedRows.length === 0 ? (
                        <p style={{ fontStyle: "italic" }}>
                            No hours logged yet for this engagement.
                        </p>
                    ) : (
                        <table className="data-table">
                            <thead>
                                <tr>
                                    <th>Date</th>
                                    <th>Description</th>
                                    <th>Hours</th>
                                    <th>Rate</th>
                                    <th>Amount</th>
                                </tr>
                            </thead>
                            <tbody>
                                {loggedRows.map((row, i) => (
                                    <tr key={i}>
                                        <td>{row.date}</td>
                                        <td>{row.description}</td>
                                        <td>{row.hours}</td>
                                        <td>
                                            {row.rate} {invoice.currency}
                                        </td>
                                        <td>
                                            {row.amount} {invoice.currency}
                                        </td>
                                    </tr>
                                ))}
                                <tr>
                                    <td colSpan={2}>
                                        <strong>Total</strong>
                                    </td>
                                    <td>
                                        <strong>{invoice.totalHours}</strong>
                                    </td>
                                    <td></td>
                                    <td>
                                        <strong>
                                            {invoice.totalAmount}{" "}
                                            {invoice.currency}
                                        </strong>
                                    </td>
                                </tr>
                            </tbody>
                        </table>
                    )}
                </>
            )}
        </div>
    );
}

export default ClientDetailsPanel;
