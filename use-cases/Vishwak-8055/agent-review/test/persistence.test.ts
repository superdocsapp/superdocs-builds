import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { InMemoryBackend, JsonFileBackend } from "../src/persistence";

describe("InMemoryBackend", () => {
  it("round-trips values and supports prefix listing", () => {
    const backend = new InMemoryBackend();
    backend.set("change:a", { id: "a" });
    backend.set("change:b", { id: "b" });
    backend.set("turn:1", { x: 1 });
    expect(backend.get("change:a")).toEqual({ id: "a" });
    expect(backend.listKeys("change:").sort()).toEqual(["change:a", "change:b"]);
  });

  it("delete removes a key", () => {
    const backend = new InMemoryBackend();
    backend.set("k", 1);
    backend.delete("k");
    expect(backend.get("k")).toBeUndefined();
  });
});

describe("JsonFileBackend", () => {
  let dir: string;
  beforeEach(() => {
    dir = fs.mkdtempSync(path.join(os.tmpdir(), "superdocs-review-test-"));
  });
  afterEach(() => {
    fs.rmSync(dir, { recursive: true, force: true });
  });

  it("round-trips a value through real disk I/O", () => {
    const backend = new JsonFileBackend(dir);
    backend.set("change:a", { id: "a", nested: { n: 1 } });
    expect(backend.get("change:a")).toEqual({ id: "a", nested: { n: 1 } });
  });

  it("survives being re-opened against the same directory (simulates extension/VS Code restart)", () => {
    const first = new JsonFileBackend(dir);
    first.set("change:a", { id: "a" });

    const second = new JsonFileBackend(dir); // fresh instance, same dir
    expect(second.get("change:a")).toEqual({ id: "a" });
  });

  it("returns undefined for a missing key rather than throwing", () => {
    const backend = new JsonFileBackend(dir);
    expect(backend.get("nope")).toBeUndefined();
  });

  it("listKeys only returns real records, never leftover temp files", () => {
    const backend = new JsonFileBackend(dir);
    backend.set("change:a", { id: "a" });
    backend.set("change:b", { id: "b" });
    expect(backend.listKeys("change:").sort()).toEqual(["change:a", "change:b"]);
    const filesOnDisk = fs.readdirSync(dir);
    expect(filesOnDisk.every((f) => !f.includes(".tmp-"))).toBe(true);
  });

  it("delete removes the file", () => {
    const backend = new JsonFileBackend(dir);
    backend.set("k", { v: 1 });
    backend.delete("k");
    expect(backend.get("k")).toBeUndefined();
    expect(backend.listKeys("")).toEqual([]);
  });
});
