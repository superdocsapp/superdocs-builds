import { Router } from "express";
import {
    createEngagement,
    listEngagementsForClient,
} from "../repositories/engagements.js";

const router = Router();

router.post("/", async (req, res) => {
    const engagement = await createEngagement(req.body);
    res.json(engagement);
});

router.get("/client/:clientId", async (req, res) => {
    const engagements = await listEngagementsForClient(req.params.clientId);
    res.json(engagements);
});

export default router;
