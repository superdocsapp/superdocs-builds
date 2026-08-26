import express from "express";
import twilio from "twilio";
import { helpText, parseSms } from "./parser.js";

export function createApp({ config, bridge, twilioClient, logger = console }) {
  const app = express();
  const processed = new Map();
  app.use(express.urlencoded({ extended: false }));
  app.get("/health", (_req, res) => res.json({ ok: true }));
  if (config.resultsDir) {
    app.use("/files", express.static(config.resultsDir, {
      dotfiles: "deny",
      fallthrough: false,
      index: false
    }));
  }

  app.post("/twilio/inbound", async (req, res) => {
    const { From: from, Body: body, MessageSid: messageSid } = req.body;
    const webhookUrl = `${config.publicBaseUrl}/twilio/inbound`;
    const signature = req.get("X-Twilio-Signature") || "";
    if (config.validateTwilioSignatures && !twilio.validateRequest(config.twilioAuthToken, signature, webhookUrl, req.body)) {
      logger.warn(JSON.stringify({ event: "sms.rejected", reason: "invalid_twilio_signature", messageSid }));
      return res.status(403).send("Forbidden");
    }
    if (!from || !body || !messageSid) return res.status(400).send("Missing Twilio From, Body, or MessageSid");
    if (processed.has(messageSid)) return res.type("text/xml").send("<Response/>");
    processed.set(messageSid, Date.now());
    logger.info(JSON.stringify({ event: "sms.received", messageSid, from, body: config.logMessageBody ? body : "[redacted]" }));
    res.type("text/xml").send("<Response/>");

    try {
      const job = parseSms(body);
      const link = await bridge.run({ messageSid, ...job });
      await twilioClient.messages.create({ to: from, from: config.twilioPhoneNumber, body: `Done: ${link}` });
      logger.info(JSON.stringify({ event: "sms.completed", messageSid, from, resultUrl: link }));
    } catch (error) {
      const message = error.message.startsWith("Use:") || error.message.includes("needs an HTTPS") ? `${error.message}\n${helpText}` : "Sorry, I could not process that document. Please check the link and try again.";
      await twilioClient.messages.create({ to: from, from: config.twilioPhoneNumber, body: message.slice(0, 1500) });
      logger.error(JSON.stringify({ event: "sms.failed", messageSid, from, error: error.message }));
    }
  });
  return app;
}
