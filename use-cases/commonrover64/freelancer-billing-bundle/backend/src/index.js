import express from "express";
import dotenv from "dotenv";
import clientsRouter from "./routes/clientsRoute.js";
import engagementsRouter from "./routes/engagementsRoute.js";
import timesheetEntriesRouter from "./routes/timesheetEntriesRoute.js";
import invoicesRoute from "./routes/invoicesRoute.js";
import documentsRouter from "./routes/documentsRoute.js"
import { runMigrations } from "./db/migrate.js";

dotenv.config();

const app = express();
app.use(express.json());

runMigrations();

app.use("/clients", clientsRouter);
app.use("/engagements", engagementsRouter);
app.use("timesheet-entries", timesheetEntriesRouter);
app.use("/invoices", invoicesRoute);
app.use("/documents", documentsRouter)

const PORT = process.env.PORT || 3001;
app.listen(PORT, () => {
    console.log(`Server started on port ${PORT}`);
});
