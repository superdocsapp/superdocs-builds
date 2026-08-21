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
        res.json(result);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

export default router;
