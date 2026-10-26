import pg from "pg";
import dotenv from "dotenv";

dotenv.config();

// Postgres DATE columns come back as JS Date objects by default, which introduces timezone shifts when formatted (a stored date can display as
// the previous day). DATE has no time component, so we tell pg to return it as the raw 'YYYY-MM-DD' string instead, avoiding Date object math entirely.
pg.types.setTypeParser(1082, (value) => value);

// One shared pool for the whole app. Neon handles connection pooling on
// their end too, but this avoids opening a new connection per query.
export const pool = new pg.Pool({
    connectionString: process.env.DATABASE_URL,
});
