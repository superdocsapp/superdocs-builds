/**
 * Server-side SuperDocs configuration.
 * Never import this module from Client Components.
 */

export function getSuperDocsApiKey(): string {
  const key = process.env.SUPERDOCS_API_KEY?.trim();
  if (!key) {
    throw new Error("SUPERDOCS_API_KEY is not configured");
  }
  return key;
}
