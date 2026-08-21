import { Router } from "express";
import { getEngagementById } from "../repositories/engagements.js";
import { getRateHistoryForClient } from "../repositories/rateCards.js";
import { getTimesheetForEngagement } from "../repositories/timesheetEntries.js";
import { mapRateRow, mapTimesheetRow } from "../helpers/mappers.js";
import { splitInvoiceByRate } from "../billing/invoice.js";

const router = Router();

router.get("/engagement/:engagementId", async (req, res) => {
    const engagement = await getEngagementById(req.params.engagementId);

    if (!engagement) {
        return res.status(404).json({ error: "Engagement not found" });
    }
    const rateRows = await getRateHistoryForClient(engagement.client_id);
    const timesheetRows = await getTimesheetForEngagement(engagement.id);

    const rateHistory = rateRows.map(mapRateRow);
    const timesheet = timesheetRows.map(mapTimesheetRow);

    const invoice = splitInvoiceByRate(timesheet, rateHistory);

    res.json({
        engagement,
        invoice,
    });
});

export default router;
