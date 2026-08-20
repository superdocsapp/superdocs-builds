import { createAppAuth } from "@octokit/auth-app";
import { Octokit } from "octokit";
import type { AppConfig } from "../config.js";

export type InstallationClientFactory = (
  installationId: number
) => Promise<Octokit>;

export type GitHubAppCredentials = {
  appId: string;
  privateKey: string;
};

/**
 * Reads GitHub App credentials from config, or reports why they are unusable.
 *
 * The private key is supplied base64-encoded so it survives a single-line
 * environment variable without embedded newlines being mangled. It is decoded here
 * and never logged.
 */
export function readAppCredentials(
  config: AppConfig
): { ok: true; credentials: GitHubAppCredentials } | { ok: false; reason: string } {
  if (config.GITHUB_APP_ID === "") {
    return { ok: false, reason: "GITHUB_APP_ID is not set" };
  }

  if (config.GITHUB_PRIVATE_KEY_BASE64 === "") {
    return { ok: false, reason: "GITHUB_PRIVATE_KEY_BASE64 is not set" };
  }

  const privateKey = Buffer.from(
    config.GITHUB_PRIVATE_KEY_BASE64,
    "base64"
  ).toString("utf8");

  if (!privateKey.includes("PRIVATE KEY")) {
    return {
      ok: false,
      reason:
        "GITHUB_PRIVATE_KEY_BASE64 did not decode to a PEM private key. Base64-encode the .pem file GitHub gave you."
    };
  }

  return {
    ok: true,
    credentials: { appId: config.GITHUB_APP_ID, privateKey }
  };
}

/**
 * Builds a factory that returns an Octokit authenticated as one installation.
 *
 * Clients are cached per installation for the life of the process. Installation
 * tokens expire after an hour, and Octokit's app auth strategy refreshes them, so
 * caching the client is safe while caching a raw token would not be.
 */
export function createInstallationClientFactory(
  credentials: GitHubAppCredentials
): InstallationClientFactory {
  const cache = new Map<number, Octokit>();

  return async (installationId: number) => {
    const cached = cache.get(installationId);
    if (cached) return cached;

    const octokit = new Octokit({
      authStrategy: createAppAuth,
      auth: {
        appId: credentials.appId,
        privateKey: credentials.privateKey,
        installationId
      }
    });

    cache.set(installationId, octokit);
    return octokit;
  };
}
