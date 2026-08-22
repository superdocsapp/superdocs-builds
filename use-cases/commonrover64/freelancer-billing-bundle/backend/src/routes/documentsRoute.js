import { Router } from "express";
import {
    resumeAfterReview,
    startDocumentGeneration,
} from "../services/documentGenerationService.js";

const router = Router();

// start generating a document. Body: { sessionId, filename, skeletonHtml, instruction }
// reeturns pendingChanges for the frontend to show a human before anything is approved.
router.post("/generate", async (req, res) => {
    try {
        const result = await startDocumentGeneration(req.body);
        res.json(result);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// submit human review decisions and export. Body: { sessionId, jobId, decisions, exportFormat }
router.post("/review", async (req, res) => {
    try {
        const result = await resumeAfterReview(req.body);

        // If a fresh round of changes came back (denial triggered a revision),
        // there's nothing to export yet, just return the JSON as-is.
        if (result.status === "awaiting_approval") {
            return res.json(result);
        }

        const { exportResult } = result;
        // Export came back as raw file bytes, send it as an actual downloadable file
        // instead of dumping the buffer into a JSON response.
        if (exportResult?.isBinary) {
            res.setHeader(
                "Content-Type",
                exportResult.contentType || "application/octet-stream",
            );
            if (exportResult.contentDisposition) {
                res.setHeader(
                    "Content-Disposition",
                    exportResult.contentDisposition,
                );
            } else {
                res.setHeader(
                    "Content-Disposition",
                    'attachment; filename = "document.docx"',
                );
            }
            return res.send(exportResult.buffer);
        }

        // Export came back as JSON (e.g. a download URL), return it normally.
        res.json(result)
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

export default router;
