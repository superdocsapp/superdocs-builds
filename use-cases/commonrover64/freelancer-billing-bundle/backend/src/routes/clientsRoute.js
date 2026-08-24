import { Router } from "express";
import { createClient, listClients } from "../repositories/clients.js";
import {
    createRateCard,
    getRateHistoryForClient,
} from "../repositories/rateCards.js";

const router = Router();

router.post("/", async (req, res) => {
    const client = await createClient(req.body);
    res.json(client);
});

router.get("/", async (req, res) => {
    const clients = await listClients();
    res.json(clients);
});

router.post("/:clientId/rate-cards", async (req, res) => {
    const rateCard = await createRateCard({
        clientId: req.params.clientId,
        ...req.body,
    });
    res.json(rateCard);
});

router.get("/:clientId/rate-cards", async (req, res) => {
    try {
        const rates = await getRateHistoryForClient(req.params.clientId);
        res.json(rates);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

export default router;
