/**
 * One caller racing for one key. faults.test.ts spawns a crowd of these at
 * once, which tests the cross-process claim rather than an in-process lock —
 * the harder case, and the one two workers on a box actually hit.
 *
 * Exit 0: this process executed the operation or replayed its result.
 * Exit 3: this process was told another caller holds the key.
 *
 * The children busy-wait on a start file before racing. Without it, process
 * spawn overhead staggers them by tens of milliseconds and they never actually
 * collide — which mutation testing proved: weakening BEGIN IMMEDIATE to BEGIN
 * DEFERRED went undetected until this barrier was added.
 */

import { existsSync } from "node:fs";

import { Idempotent, OutcomeUnknown, Policy } from "../src/index.ts";
import { FakeServer } from "./harness.ts";

const [storePath, serverPath, key, policyPath, gate] = process.argv.slice(2);

if (gate) {
  const deadline = Date.now() + 10_000;
  while (!existsSync(gate) && Date.now() < deadline) {
    // spin: a sleep here would reintroduce the stagger this exists to remove
  }
}

const idem = new Idempotent(storePath!, Policy.load(policyPath!));
const server = new FakeServer(serverPath!);

// Race on many keys rather than one. Twelve processes contending once is
// twelve chances to hit the window where two callers both see 'absent'; racing
// across a batch of keys turns that into hundreds. Mutation testing showed the
// single-key version could not tell BEGIN IMMEDIATE from BEGIN DEFERRED.
const KEYS = 60;
let held = 0;

for (let n = 0; n < KEYS; n++) {
  const k = `${key}-${n}`;
  try {
    idem.run(k, () => server.chatAsync(k));
  } catch (error) {
    if (error instanceof OutcomeUnknown) {
      held++; // another caller holds it: correct, and not an error
      continue;
    }
    console.error(error);
    process.exit(1);
  }
}

process.exit(held === KEYS ? 3 : 0);
