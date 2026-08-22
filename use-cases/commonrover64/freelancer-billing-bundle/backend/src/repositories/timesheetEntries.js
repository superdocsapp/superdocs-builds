import { pool } from "../db/pool.js";

// log a single timesheet entry against an engagement
export async function createTimesheetEntry({
    engagementId,
    entryDate,
    hours,
    description,
}) {
    const result = await pool.query(
        `INSERT INTO timesheet_entries (engagement_id, entry_date, hours, description) VALUES ($1, $2, $3, $4)
        RETURNING *`,
        [engagementId, entryDate, hours, description],
    );
    return result.rows[0];
}

export async function getTimesheetForEngagement(engagementId) {
    const result = await pool.query(
        `SELECT * FROM timesheet_entries
        WHERE engagement_id = $1
        ORDER BY entry_date ASC`,
        [engagementId],
    );
    return result.rows;
}

