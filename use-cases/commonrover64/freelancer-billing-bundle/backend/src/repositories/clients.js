import { pool } from "../db/pool.js";

export async function createClient({ name, email, phone, address }) {
    const result = await pool.query(
        `INSERT INTO clients (name, email, phone, address)
        VALUES ($1, $2, $3, $4)
        RETURNING *`,
        [name, email, phone, address],
    );
    return result.rows[0];
}

// Fetch a single client by id, or undefined if not found.
export async function getClientById(id) {
    const result = await pool.query(`SELECT * FROM clients WHERE id = $1`, [
        id,
    ]);
    return result.rows[0];
}

// List all clients, most recently created first.
export async function listClients() {
    const result = await pool.query(`SELECT * FROM clients ORDER BY id DESC`);
    return result.rows;
}
