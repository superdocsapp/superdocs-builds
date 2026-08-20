import express from "express";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createTailorRouter } from "./routes/tailor.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export function createApp({ sessionFactory, llm } = {}) {
  const app = express();
  app.use(express.static(path.join(__dirname, "..", "public")));
  app.use("/api/tailor", createTailorRouter({ sessionFactory, llm }));
  return app;
}