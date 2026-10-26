import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { pool } from "./pool.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const migrationsDir = path.join(__dirname, "migrations");

export async function runMigrations() {
    // Table that remembers which migration files have already run.
    await pool.query(`
    CREATE TABLE IF NOT EXISTS schema_migrations (
      filename TEXT PRIMARY KEY,
      applied_at TIMESTAMP DEFAULT now()
    );
  `);

    const files = fs.readdirSync(migrationsDir).sort();

    for (const file of files) {
        const alreadyApplied = await pool.query(
            "SELECT 1 FROM schema_migrations WHERE filename = $1",
            [file],
        );

        if (alreadyApplied.rows.length > 0) {
            console.log(`Skipping already-applied migration: ${file}`);
            continue;
        }

        const sql = fs.readFileSync(path.join(migrationsDir, file), "utf-8");
        console.log(`Running migration: ${file}`);
        await pool.query(sql);

        await pool.query(
            "INSERT INTO schema_migrations (filename) VALUES ($1)",
            [file],
        );
    }

    console.log("All migrations applied.");
}

// Only run + exit if this file is executed directly (npm run migrate),
// not when imported by index.js cause we are reusing the same pool for the app.
if (import.meta.url === `file://${process.argv[1]}`) {
    runMigrations()
        .then(() => pool.end())
        .catch((err) => {
            console.error("Migration failed:", err);
            process.exit(1);
        });
}
