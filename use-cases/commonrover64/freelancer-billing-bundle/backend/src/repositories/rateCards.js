import { pool } from "../db/pool.js";

// Insert a new rate for a client. A new row here = a rate change from that date forward.
export async function createRateCard({
    clientId,
    hourlyRate,
    currency,
    effectiveFrom,
}) {
    const result = await pool.query(
        `INSERT INTO rate_cards (client_id, hourly_rate, currency, effective_from)
        VALUES ($1, $2, $3, $4)
        RETURNING *`,
        [clientId, hourlyRate, currency, effectiveFrom],
    );
    return result.rows[0];
}

// Full rate history for a client, oldest first — this is exactly the shape splitInvoiceByRate expects as its rateHistory argument.
export async function getRateHistoryForClient(clientId) {
    const result = await pool.query(
        `SELECT * FROM rate_cards WHERE client_id = $1
        ORDER BY effective_from ASC`,
        [clientId],
    );
    return result.rows;
}
