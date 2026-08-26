import { writeFile } from "node:fs/promises";
import { mkdir } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import type { SuperDocsClient } from "./client.js";
import type { Logger } from "./logger.js";

const TAKEOVER_CODE_PATH = path.join(os.homedir(), ".superdocs", "takeover-code.txt");

export async function handoffAccount(
  client: SuperDocsClient,
  logger: Logger,
  email: string,
  workingContext: string,
): Promise<void> {
  const { takeover_code } = await client.handoff({ email, working_context: workingContext });

  logger.success(`handoff email sent to ${email}`);
  console.log(`\n${"=".repeat(50)}\n  TAKEOVER CODE: ${takeover_code}\n${"=".repeat(50)}\n`);

  await mkdir(path.dirname(TAKEOVER_CODE_PATH), { recursive: true });
  await writeFile(TAKEOVER_CODE_PATH, takeover_code, "utf8");
  logger.info(`code also saved to ${TAKEOVER_CODE_PATH}`);

  console.log(
    `Your operator should open the one-time link emailed to ${email}, sign in, and enter the code above. That adopts this SuperDocs account IN PLACE — this agent keeps its API key and all its work; nothing needs to be redone.`,
  );

  // Never email this code or post it anywhere public. It's the anti-phishing
  // gate proving whoever enters it actually received the email and is the
  // real operator — not just whoever the email happened to reach.
}
