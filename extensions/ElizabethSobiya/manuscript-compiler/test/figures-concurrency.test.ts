/**
 * Figure upload under concurrency.
 *
 * An illustrated 300-page book carries ~120 plates. Uploading them one at a time
 * meant an export sat still for the better part of a minute doing nothing but
 * waiting on round trips. Running them in parallel is the obvious fix and brings
 * two non-obvious problems with it, both covered here:
 *
 *   - content-addressing stops working for free. Serially, the second copy of an
 *     image always found the first in the cache; concurrently, both can start
 *     before either finishes and the same bytes go up twice.
 *   - unbounded parallelism trades a slow export for a rate-limited one.
 */

import { describe, expect, it, vi } from "vitest";
import { uploadFigures } from "../src/superdocs/figures";
import type { AssignedFigure } from "../src/core/numbering";
import type { SuperDocsClient } from "../src/superdocs/client";
import { MemoryVault } from "./helpers";

function figure(name: string, index: number): AssignedFigure {
  return {
    key: name,
    label: `Figure ${index + 1}`,
    caption: "",
    sourcePath: `img/${name}.png`,
    chapterOrder: index,
    anchor: `fig-${name}`,
  };
}

/** A client that records concurrency and resolves after a turn of the event loop. */
function recordingClient() {
  let inFlight = 0;
  let peak = 0;
  const calls: string[] = [];
  const client = {
    uploadImage: vi.fn(async ({ filename }: { base64: string; filename: string }) => {
      inFlight += 1;
      peak = Math.max(peak, inFlight);
      calls.push(filename);
      await new Promise((r) => setTimeout(r, 5));
      inFlight -= 1;
      return { url: `https://cdn.example/${filename}` };
    }),
  } as unknown as SuperDocsClient;
  return { client, calls, peak: () => peak };
}

describe("uploading a book's worth of figures", () => {
  it("uploads distinct images in parallel rather than one at a time", async () => {
    const vault = new MemoryVault({});
    const figures: AssignedFigure[] = [];
    for (let i = 0; i < 24; i += 1) {
      vault.setBinary(`img/p${i}.png`, new Uint8Array([i, i + 1, i + 2, 9]));
      figures.push(figure(`p${i}`, i));
    }
    const { client, peak } = recordingClient();

    const result = await uploadFigures({
      html: figures.map((f) => `<img src="${f.sourcePath}">`).join(""),
      figures,
      vault,
      client,
      cache: {},
      concurrency: 6,
    });

    expect(result.uploaded).toBe(24);
    // Actually concurrent — a serial implementation never exceeds one in flight.
    expect(peak()).toBeGreaterThan(1);
  });

  it("never exceeds the concurrency limit it was given", async () => {
    const vault = new MemoryVault({});
    const figures: AssignedFigure[] = [];
    for (let i = 0; i < 30; i += 1) {
      vault.setBinary(`img/q${i}.png`, new Uint8Array([200, i, i * 2, 7]));
      figures.push(figure(`q${i}`, i));
    }
    const { client, peak } = recordingClient();

    await uploadFigures({
      html: "",
      figures,
      vault,
      client,
      cache: {},
      concurrency: 4,
    });

    expect(peak()).toBeLessThanOrEqual(4);
  });

  it("uploads identical bytes once even when both copies start together", async () => {
    // The regression that parallelism introduces: two plates with the same content
    // racing each other past the cache check.
    const vault = new MemoryVault({});
    const same = new Uint8Array([42, 42, 42, 42]);
    const figures: AssignedFigure[] = [];
    for (let i = 0; i < 8; i += 1) {
      vault.setBinary(`img/dup${i}.png`, same);
      figures.push(figure(`dup${i}`, i));
    }
    const { client, calls } = recordingClient();

    const result = await uploadFigures({
      html: figures.map((f) => `<img src="${f.sourcePath}">`).join(""),
      figures,
      vault,
      client,
      cache: {},
      concurrency: 8,
    });

    expect(calls).toHaveLength(1);
    expect(result.uploaded).toBe(1);
    expect(result.reused).toBe(7);
    // Every copy still points at the hosted URL, not just the one that uploaded.
    expect(result.html.match(/https:\/\/cdn\.example/g)).toHaveLength(8);
  });

  it("still reuses URLs carried over from a previous compile", async () => {
    const vault = new MemoryVault({});
    vault.setBinary("img/a.png", new Uint8Array([1, 2, 3]));
    const figures = [figure("a", 0)];
    const { client, calls } = recordingClient();

    const cache: Record<string, string> = {};
    const first = await uploadFigures({
      html: '<img src="img/a.png">',
      figures,
      vault,
      client,
      cache,
    });
    const second = await uploadFigures({
      html: '<img src="img/a.png">',
      figures,
      vault,
      client,
      cache,
    });

    expect(first.uploaded).toBe(1);
    expect(second.uploaded).toBe(0);
    expect(second.reused).toBe(1);
    expect(calls).toHaveLength(1);
  });

  it("stops when cancelled and says how far it got", async () => {
    const vault = new MemoryVault({});
    const figures: AssignedFigure[] = [];
    for (let i = 0; i < 40; i += 1) {
      vault.setBinary(`img/c${i}.png`, new Uint8Array([1, i, 3, 4]));
      figures.push(figure(`c${i}`, i));
    }
    const { client, calls } = recordingClient();
    const signal = { aborted: false };

    const result = await uploadFigures({
      html: "",
      figures,
      vault,
      client,
      cache: {},
      concurrency: 4,
      signal,
      onProgress: (done) => {
        if (done >= 8) signal.aborted = true;
      },
    });

    expect(calls.length).toBeLessThan(40);
    expect(result.diagnostics.some((d) => d.code === "figure.upload_cancelled")).toBe(true);
  });

  it("one unreadable plate does not stop the other figures", async () => {
    const vault = new MemoryVault({});
    vault.setBinary("img/good.png", new Uint8Array([1, 2, 3]));
    // img/missing.png is deliberately absent.
    const { client } = recordingClient();

    const result = await uploadFigures({
      html: '<img src="img/good.png"><img src="img/missing.png">',
      figures: [figure("good", 0), figure("missing", 1)],
      vault,
      client,
      cache: {},
      concurrency: 4,
    });

    expect(result.uploaded).toBe(1);
    expect(result.diagnostics.some((d) => d.code === "figure.unreadable")).toBe(true);
    expect(result.html).toContain("https://cdn.example/good.png");
  });
});
