import { pool } from "../db/pool.js";

// insert a new engagement (a piece of work) for a client.
export async function createEngagement({ clientId, title, startDate }) {
    const result = await pool.query(
        `INSERT INTO engagements (client_id, title, start_date) VALUES ($1, $2, $3)
        RETURNING *`,
        [clientId, title, startDate],
    );
    return result.rows[0];
}

// fetch a single engagement by id.
export async function getEngagementById(id) {
    const result = await pool.query(`SELECT * FROM engagements WHERE id = $1`, [
        id,
    ]);
    return result.rows[0];
}

// list all engagements for a given client.
export async function listEngagementsForClient(clientId) {
    const result = await pool.query(
        `SELECT * FROM engagements WHERE client_id = $1 ORDER BY start_date DESC`,
        [clientId],
    );
    return result.rows;
}
