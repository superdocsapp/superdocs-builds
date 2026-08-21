import pg from "pg";
import dotenv from "dotenv";

dotenv.config();

// One shared pool for the whole app. Neon handles connection pooling on
// their end too, but this avoids opening a new connection per query.
export const pool = new pg.Pool({
    connectionString: process.env.DATABASE_URL,
});
