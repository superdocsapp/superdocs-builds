import { Router } from "express";
import {
    createTimesheetEntry,
    getTimesheetForEngagement,
} from "../repositories/timesheetEntries.js";

const router = Router();

router.post("/:engagementId", async (req, res) => {
    const entry = await createTimesheetEntry({
        engagementId: req.params.engagementId,
        ...req.body,
    });
    res.json(entry);
});

router.get("/:engagementId", async (req, res) => {
    const entries = await getTimesheetForEngagement(req.params.engagementId);
    res.json(entries);
});

export default router;
