import "dotenv/config";
import { z } from "zod";

const envSchema = z.object({
  NODE_ENV: z
    .enum(["development", "test", "production"])
    .default("development"),
  PORT: z.coerce.number().int().positive().default(3000),
  LOG_LEVEL: z
    .enum(["fatal", "error", "warn", "info", "debug", "trace", "silent"])
    .default("info"),
  GITHUB_APP_ID: z.string().optional().default(""),
  GITHUB_WEBHOOK_SECRET: z.string().optional().default(""),
  GITHUB_PRIVATE_KEY_BASE64: z.string().optional().default(""),
  SUPERDOCS_API_KEY: z.string().optional().default(""),
  SUPERDOCS_API_BASE_URL: z.string().url().default("https://api.superdocs.app"),
  DATABASE_URL: z.string().default("file:./data/dev.sqlite"),
  ARTIFACTS_DIR: z.string().default("./artifacts"),
  PUBLIC_ARTIFACT_BASE_URL: z.preprocess(
    (value) => (value === "" ? undefined : value),
    z.string().url().optional()
  )
});

export type AppConfig = z.infer<typeof envSchema>;

export function loadConfig(env: NodeJS.ProcessEnv = process.env): AppConfig {
  return envSchema.parse(env);
}
