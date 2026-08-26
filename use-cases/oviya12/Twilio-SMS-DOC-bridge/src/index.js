import path from "node:path";
import { fileURLToPath } from "node:url";
import twilio from "twilio";
import { createApp } from "./app.js";
import { SuperDocsService } from "./superdocs.js";

const required = ["PUBLIC_BASE_URL", "SUPERDOCS_API_KEY", "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_PHONE_NUMBER"];
for (const name of required) if (!process.env[name]) throw new Error(`Missing required environment variable: ${name}`);
const config = {
  port: Number(process.env.PORT || 3000),
  publicBaseUrl: process.env.PUBLIC_BASE_URL,
  twilioAuthToken: process.env.TWILIO_AUTH_TOKEN,
  twilioPhoneNumber: process.env.TWILIO_PHONE_NUMBER,
  validateTwilioSignatures: process.env.TWILIO_VALIDATE_SIGNATURES !== "false",
  logMessageBody: process.env.LOG_MESSAGE_BODY !== "false"
};
const root = path.dirname(fileURLToPath(import.meta.url));
const resultsDir = path.join(root, "..", "results");
const bridge = new SuperDocsService({
  apiKey: process.env.SUPERDOCS_API_KEY,
  baseUrl: process.env.SUPERDOCS_BASE_URL || "https://api.superdocs.app",
  publicBaseUrl: config.publicBaseUrl,
  resultsDir,
  maxDocumentBytes: Number(process.env.MAX_DOCUMENT_BYTES || 10 * 1024 * 1024)
});
const twilioClient = twilio(process.env.TWILIO_ACCOUNT_SID, process.env.TWILIO_AUTH_TOKEN);
createApp({ config: { ...config, resultsDir }, bridge, twilioClient }).listen(config.port, () => console.log(`SMS bridge listening on :${config.port}`));
