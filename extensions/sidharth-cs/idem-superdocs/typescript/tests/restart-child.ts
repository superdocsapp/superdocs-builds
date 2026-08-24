/**
 * Claims an operation key, sends the request, and dies before recording the
 * outcome. Run as a subprocess by faults.test.ts.
 *
 * SIGKILL to its own pid, not process.exit: no exit handlers, no flushing, no
 * unwinding. It is the closest thing to pulling the power cord that a test can
 * do, and it is the only honest way to prove the record survives (N4).
 */

import { Idempotent, Policy } from "../src/index.ts";
import { FakeServer } from "./harness.ts";

const [storePath, serverPath, key, policyPath] = process.argv.slice(2);

const idem = new Idempotent(storePath!, Policy.load(policyPath!));
const server = new FakeServer(serverPath!);

idem.run(key!, () => {
  server.chatAsync(key!);
  // The edit is applied and the server answered. This process now dies holding
  // that answer, exactly as a crash between the response and the commit would.
  process.kill(process.pid, "SIGKILL");
});
