import { createHmac, timingSafeEqual } from "node:crypto";

const SIGNATURE_PREFIX = "sha256=";

export function createGitHubSignature(payload: string, secret: string): string {
  const digest = createHmac("sha256", secret).update(payload).digest("hex");
  return `${SIGNATURE_PREFIX}${digest}`;
}

export function verifyGitHubSignature({
  payload,
  signature,
  secret
}: {
  payload: string;
  signature?: string;
  secret: string;
}): boolean {
  if (!secret || !signature?.startsWith(SIGNATURE_PREFIX)) {
    return false;
  }

  const expected = createGitHubSignature(payload, secret);
  const actualBuffer = Buffer.from(signature);
  const expectedBuffer = Buffer.from(expected);

  if (actualBuffer.length !== expectedBuffer.length) {
    return false;
  }

  return timingSafeEqual(actualBuffer, expectedBuffer);
}

