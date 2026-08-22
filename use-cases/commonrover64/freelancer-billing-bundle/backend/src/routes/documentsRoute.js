import { Router } from "express";
import {
    resumeAfterReview,
    startDocumentGeneration,
} from "../services/documentGenerationService.js";
import {
    buildEngagementLetter,
    buildInvoice,
    buildPaymentReminder,
    buildTimesheet,
} from "../services/documentTemplates.js";
import { getEngagementById } from "../repositories/engagements.js";
import { getClientById } from "../repositories/clients.js";
import { getRateHistoryForClient } from "../repositories/rateCards.js";
import { mapRateRow, mapTimesheetRow } from "../helpers/mappers.js";
import { getTimesheetForEngagement } from "../repositories/timesheetEntries.js";
import { splitInvoiceByRate } from "../billing/invoice.js";

const router = Router();

const templateBuilders = {
    "engagement-letter": buildEngagementLetter,
    timesheet: buildTimesheet,
    invoice: buildInvoice,
    "payment-reminder": buildPaymentReminder,
};

// generates any of the 4documentt types for a real engagement, pulling live data from db
router.post("/generate/:type/:engagementId", async (req, res) => {
    try {
        const { type, engagementId } = req.params;
        const builder = templateBuilders[type];

        if (!builder) {
            return res
                .status(400)
                .json({ error: `unknown document type: ${type}` });
        }

        const engagement = await getEngagementById(engagementId);
        if (!engagement) {
            return res.status(404).json({ error: `Engagement not found` });
        }

        const client = await getClientById(engagement.client_id);
        const rateRows = await getRateHistoryForClient(engagement.client_id);
        const rateHistory = rateRows.map(mapRateRow);

        const timesheetRows = await getTimesheetForEngagement(engagementId);
        const timesheet = timesheetRows.map(mapTimesheetRow);

        const invoice = splitInvoiceByRate(timesheet, rateHistory);

        const { filename, skeletonHtml, instruction } = builder({
            client,
            engagement,
            rateHistory,
            timesheet,
            invoice,
        });

        const sessionId = `${type}-${engagementId}-${Date.now()}`;

        const result = await startDocumentGeneration({
            sessionId,
            filename,
            skeletonHtml,
            instruction,
        });

        res.json(result);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// submit human review decisions and export. Body: { sessionId, jobId, decisions, exportFormat }
router.post("/review", async (req, res) => {
    try {
        const result = await resumeAfterReview(req.body);

        if (
            result.status === "awaiting_approval" ||
            result.status === "failed_needs_manual_retry" ||
            result.status === "completed_but_incomplete"
        ) {
            return res.json(result);
        }

        const { exportResult } = result;

        if (exportResult?.isBinary) {
            res.setHeader(
                "Content-Type",
                exportResult.contentType || "application/octet-stream",
            );
            res.setHeader(
                "Content-Disposition",
                exportResult.contentDisposition ||
                    'attachment; filename="document.docx"',
            );
            return res.send(exportResult.buffer);
        }

        res.json(result);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

export default router;
