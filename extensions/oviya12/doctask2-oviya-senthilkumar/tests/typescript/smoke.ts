/**
 * Smoke test: drive the GENERATED TypeScript (axios) client against the Prism
 * mock. Proves the generated client is usable end-to-end — it builds the request
 * from the spec, calls the mock, and returns a typed UserProfileResponse.
 * No API key, no live service.
 *
 * Run: npx tsx tests/typescript/smoke.ts  (with Prism mock up)
 */
import { Configuration } from "../../clients/typescript/configuration";
import { UsersApi } from "../../clients/typescript/api/users-api";

const MOCK_URL = process.env.SUPERDOCS_MOCK_URL || "http://localhost:4010";

async function main() {
  const cfg = new Configuration({ basePath: MOCK_URL, accessToken: "smoke-test-token" });
  const users = new UsersApi(cfg);

  // GET /v1/users/me — a representative typed call through the client.
  const res = await users.getCurrentUserProfileV1UsersMeGet();

  if (res.status !== 200) {
    throw new Error(`expected HTTP 200, got ${res.status}`);
  }
  if (!res.data || typeof (res.data as any).email === "undefined") {
    throw new Error("expected a typed UserProfileResponse with an `email` field");
  }
  console.log(
    `TypeScript smoke OK — ${MOCK_URL}/v1/users/me -> ${res.status}, typed body has .email`
  );
}

main().catch((e) => {
  console.error("TS smoke FAILED:", e.message);
  process.exit(1);
});
