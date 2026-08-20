import { describe, expect, it } from "vitest";
import { parseCommand } from "../src/commands/parser.js";

describe("command parser", () => {
  it("parses the no-argument commands", () => {
    for (const verb of ["review", "preview", "help"] as const) {
      const result = parseCommand(`/superdocs ${verb}`);
      expect(result).toEqual({ ok: true, command: { verb } });
    }
  });

  it("parses an apply command with a finding ID", () => {
    const result = parseCommand("/superdocs apply a1b2c3d4e5");

    expect(result).toEqual({
      ok: true,
      command: {
        verb: "apply",
        target: { kind: "finding", findingId: "a1b2c3d4e5" }
      }
    });
  });

  it("accepts a finding ID pasted with backticks or capitals", () => {
    const result = parseCommand("/superdocs apply `A1B2C3D4E5`");

    expect(result).toEqual({
      ok: true,
      command: {
        verb: "apply",
        target: { kind: "finding", findingId: "a1b2c3d4e5" }
      }
    });
  });

  it("parses apply all-safe", () => {
    const result = parseCommand("/superdocs apply all-safe");

    expect(result).toEqual({
      ok: true,
      command: { verb: "apply", target: { kind: "all-safe" } }
    });
  });

  it("tolerates leading blank lines and trailing prose", () => {
    const result = parseCommand("\n\n/superdocs apply a1b2c3d4e5\n\nthanks!");

    expect(result).toMatchObject({ ok: true });
  });

  it("rejects a comment that only mentions a command", () => {
    const result = parseCommand("I think we should run /superdocs apply a1b2c3d4e5");

    expect(result).toMatchObject({ ok: false, failure: "not-a-command" });
  });

  it("does not run a command quoted inside a code fence", () => {
    const result = parseCommand("```\n/superdocs apply a1b2c3d4e5\n```");

    expect(result).toMatchObject({ ok: false, failure: "not-a-command" });
  });

  it("does not run a command quoted in a blockquote", () => {
    const result = parseCommand("> /superdocs apply a1b2c3d4e5");

    expect(result).toMatchObject({ ok: false, failure: "not-a-command" });
  });

  it("rejects an unknown verb", () => {
    const result = parseCommand("/superdocs deploy");

    expect(result).toMatchObject({ ok: false, failure: "unknown-verb" });
  });

  it("rejects apply without a target", () => {
    const result = parseCommand("/superdocs apply");

    expect(result).toMatchObject({ ok: false, failure: "missing-finding-id" });
  });

  it("rejects a finding ID that is not a finding ID", () => {
    const result = parseCommand("/superdocs apply ../../etc/passwd");

    expect(result).toMatchObject({ ok: false, failure: "invalid-finding-id" });
  });

  it("rejects extra arguments", () => {
    expect(parseCommand("/superdocs review now")).toMatchObject({
      ok: false,
      failure: "unexpected-arguments"
    });
    expect(parseCommand("/superdocs apply a1b2c3d4e5 f6g7h8i9j0")).toMatchObject({
      ok: false,
      failure: "unexpected-arguments"
    });
  });
});
