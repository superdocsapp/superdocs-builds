// @vitest-environment jsdom

import { describe, expect, it, vi } from "vitest";
import {
  getSigmaWriterClient,
  initializeSigma,
  type SigmaWriterClient,
} from "../src/api";

describe("Sigma Writer initialization", () => {
  it("retains the client returned by init and waits for registration callback", async () => {
    const client: SigmaWriterClient = {
      dispatch: vi.fn(),
      request: vi.fn(),
    };
    let reportReady: (() => void) | undefined;
    window.SigmaSDK = {
      WRITER: {
        init(onReady) {
          reportReady = onReady;
          return client;
        },
      },
    };

    let ready = false;
    const initialization = initializeSigma().then(() => {
      ready = true;
    });
    await Promise.resolve();
    expect(ready).toBe(false);
    expect(getSigmaWriterClient()).toBe(client);

    reportReady?.();
    await initialization;
    expect(ready).toBe(true);
  });
});
