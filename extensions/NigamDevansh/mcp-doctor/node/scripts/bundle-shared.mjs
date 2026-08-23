// The published package must carry its own copy of the contract: shared/ is a
// sibling in the repo and would not exist on a user's machine.
import { cpSync, rmSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const from = join(here, "..", "..", "shared");
const to = join(here, "..", "shared");

rmSync(to, { recursive: true, force: true });
mkdirSync(to, { recursive: true });
cpSync(from, to, { recursive: true });
console.log(`bundled shared contract → ${to}`);
