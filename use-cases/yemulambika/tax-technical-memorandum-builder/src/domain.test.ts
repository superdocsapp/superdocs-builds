import { describe, expect, it } from "vitest";
import {
  authoritiesTable,
  blockers,
  caseSchema,
  deterministicTotal,
  outputs,
  parseProposedChanges,
  decideProposal,
  traceNarrative,
  verifyAuthorities,
  type Proposal,
} from "./domain";
import { scenario } from "./scenario";
import { FakeSuperDocsClient, pollBounded } from "./superdocs";
describe("tax memo evidence pipeline", () => {
  it("validates case facts", () =>
    expect(caseSchema.parse(scenario).facts).toHaveLength(2));
  it("verifies found quotes and rejects fabricated quotes", () => {
    expect(verifyAuthorities(scenario.authorities)[0].verification_status).toBe(
      "VERIFIED",
    );
    expect(
      verifyAuthorities([
        { ...scenario.authorities[0], exact_quote: "fabricated" },
      ])[0].verification_status,
    ).toBe("UNVERIFIED");
  });
  it("flags missing authority and produces complete table", () => {
    const table = authoritiesTable([
      { ...scenario.authorities[0], verification_status: "MISSING" },
    ]);
    expect(table[0]).toMatchObject({
      authority: expect.any(String),
      citation: expect.any(String),
      exact_quote: expect.any(String),
      location: expect.any(String),
      verification_status: "MISSING",
    });
  });
  it("preserves money strings and records deterministic inputs", () => {
    expect(scenario.rows[0].amount).toBe("4800000.00");
    expect(
      deterministicTotal(
        scenario.rows,
        ["EXP-001", "EXP-002"],
        "CALC-1",
        "Total",
      ),
    ).toEqual({
      source_row_id: "CALC-1",
      label: "Total",
      amount: "500000.00",
      input_row_ids: ["EXP-001", "EXP-002"],
    });
  });
  it("detects and verifies every matched narrative figure", () => {
    const r = traceNarrative(
      { Analysis: "INR 1200000 against INR 6500000.00 proceeds" },
      scenario.rows,
    );
    expect(r).toHaveLength(2);
    expect(r.every((x) => x.verified)).toBe(true);
  });
  it("blocks an unmatched figure and prevents source override", () => {
    const r = traceNarrative(
      { Analysis: "The model invented INR 999999" },
      scenario.rows,
    );
    expect(r[0].verified).toBe(false);
    expect(blockers(verifyAuthorities(scenario.authorities), r, [])).toContain(
      "Unmatched figure: INR 999999",
    );
  });
  it("unverified quote and missing authority block approval", () =>
    expect(
      blockers(
        [{ ...scenario.authorities[0], verification_status: "UNVERIFIED" }],
        [],
        [],
        ["Unsupported Ruling"],
      ),
    ).toHaveLength(2));
  it("supports independent decisions without automatic approval", () => {
    let p: Proposal[] = [
      { id: "1", section: "A", before: "", after: "a", decision: "PENDING" },
      { id: "2", section: "B", before: "", after: "b", decision: "PENDING" },
    ];
    p = decideProposal(p, "1", "APPROVED", "Checked against source");
    p = decideProposal(p, "2", "REJECTED", "Unsupported");
    p = decideProposal(p, "2", "REJECTED", "Unsupported");
    expect(p.map((x) => x.decision)).toEqual(["APPROVED", "REJECTED"]);
    expect(p.map((x) => x.reviewerNote)).toEqual([
      "Checked against source",
      "Unsupported",
    ]);
  });
  it("shares approved source state and hides internal warnings from client", () => {
    const a = verifyAuthorities(scenario.authorities),
      r = traceNarrative(
        { Analysis: "INR 1200000", Conclusion: "Supported" },
        scenario.rows,
      ),
      o = outputs(
        scenario,
        { Analysis: "INR 1200000", Conclusion: "Supported" },
        a,
        r,
        [],
      );
    expect(o.client.source_state).toBe(o.internal.source_state);
    expect(o.client).not.toHaveProperty("unsupported_authority_warnings");
  });
  it("second-parses JSON strings and rejects invalid content", () => {
    expect(parseProposedChanges('[{"change_id":"x","after":"ok"}]')[0].id).toBe(
      "x",
    );
    expect(() => parseProposedChanges("not-json")).toThrow("not valid JSON");
    expect(() => parseProposedChanges({ nope: true })).toThrow(
      "did not contain",
    );
  });
  it("prefers upstream proposal identity and fingerprints missing identities", () => {
    const duplicateHeadings = [
      { change_id: "upstream-valid", section: "Analysis", after: "Valid" },
      { id: "upstream-invalid", section: "Analysis", after: "Fabricated" },
    ];
    expect(
      parseProposedChanges(duplicateHeadings, { sessionId: "session-1" }).map(
        (proposal) => proposal.id,
      ),
    ).toEqual(["upstream-valid", "upstream-invalid"]);
    const withoutId = [{ section: "Analysis", after: "Stable content" }];
    const first = parseProposedChanges(withoutId, {
      sessionId: "session-1",
    })[0].id;
    const second = parseProposedChanges(withoutId, {
      sessionId: "session-1",
    })[0].id;
    expect(first).toMatch(/^local-[0-9a-f]{16}$/);
    expect(second).toBe(first);
    expect(
      parseProposedChanges(withoutId, { sessionId: "session-2" })[0].id,
    ).not.toBe(first);
  });
  it("rejects duplicate upstream proposal identities", () => {
    expect(() =>
      parseProposedChanges([
        { change_id: "same", after: "First" },
        { change_id: "same", after: "Second" },
      ]),
    ).toThrow("duplicate identities");
  });
  it("completes fake upload/chat/approve/export without pretending live", async () => {
    const c = new FakeSuperDocsClient(),
      u = await c.upload("x", "x"),
      j = await c.instruction(u.sessionId, "draft"),
      s = await pollBounded(c, j.jobId, 1, 0),
      p = parseProposedChanges(s.proposedChanges).map((x) => ({
        ...x,
        decision: "APPROVED" as const,
      }));
    await c.approve(u.sessionId, j.jobId, p);
    const e = await c.export(u.sessionId, "html");
    expect(c.approved).toHaveLength(2);
    expect(new TextDecoder().decode(e.bytes)).toContain("FAKE EXPORT");
  });
});
