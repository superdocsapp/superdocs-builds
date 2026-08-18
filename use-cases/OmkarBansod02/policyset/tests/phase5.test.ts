import { mkdtempSync, readFileSync, readdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { describe, expect, it, vi } from "vitest";

import {
  approveSynchronizedChangeSet,
  commitValidatedSynchronizedChange,
  proposeReturnWindowChangeSet,
  rejectSynchronizedChangeSet,
} from "@/app/policyset/changeset-workflow";
import { generatePolicyWorkspace } from "@/app/policyset/generate-workspace";
import type {
  PolicyDocumentContentStateMap,
  SuperDocsSessionDocumentView,
} from "@/app/policyset/superdocs-contract";
import {
  NORTHSTAR_GOODS_PROFILE,
  POLICY_DOCUMENT_TYPES,
  applyManagedField,
  renderPolicySet,
  type PolicyDocumentSet,
  type PolicyDocumentType,
  type Result,
} from "@/domain";
import {
  PolicySetSuperDocsSafetyError,
  PolicySetSynchronizedStartError,
  SuperDocsClient,
  SuperDocsRequestError,
  assertSynchronizedProposalCoverage,
  assertSynchronizedProposalGate,
  assertSynchronizedProposalSafety,
  getPolicyTargetedSynchronizedJob,
  runSessionLockExperiment,
  startPolicySynchronizedEdit,
  submitPolicyTargetedSynchronizedReview,
  type PendingChange,
} from "@/superdocs";

const DOCUMENT_IDS: Record<PolicyDocumentType, string> = {
  terms: "doc-terms",
  privacy: "doc-privacy",
  warranty: "doc-warranty",
  returns: "doc-returns",
};

describe("Phase 5 synchronized ChangeSet", () => {
  it("resolves the 30 to 14 ChangeSet to exactly Terms and Returns", () => {
    const workspace = generatePolicyWorkspace(NORTHSTAR_GOODS_PROFILE);
    const changeSet = unwrap(proposeReturnWindowChangeSet(workspace, 14));

    expect(changeSet.previousValue).toBe(30);
    expect(changeSet.nextValue).toBe(14);
    expect(changeSet.affectedDocuments).toEqual(["terms", "returns"]);
  });

  it("keeps the canonical profile at 30 before approval and validation", () => {
    const workspace = generatePolicyWorkspace(NORTHSTAR_GOODS_PROFILE);
    const changeSet = unwrap(proposeReturnWindowChangeSet(workspace, 14));

    expect(changeSet.status).toBe("proposed");
    expect(workspace.profile.returns.windowDays).toBe(30);
    expect(NORTHSTAR_GOODS_PROFILE.returns.windowDays).toBe(30);
  });

  it("starts two explicit pinned targeted jobs for the 30 to 14 ChangeSet, not one unpinned job", async () => {
    const workspace = generatePolicyWorkspace(NORTHSTAR_GOODS_PROFILE);
    const changeSet = unwrap(proposeReturnWindowChangeSet(workspace, 14));
    const startChat = vi.fn(
      async (input: { sessionId: string; documentId?: string; message: string }) => ({
        jobId: `job-${input.documentId}`,
        sessionId: input.sessionId,
        status: "in_progress" as const,
      }),
    );
    const client = {
      listSessionDocuments: vi.fn(async (sessionId: string) =>
        POLICY_DOCUMENT_TYPES.map((documentType) => ({
          identity: { sessionId, documentId: DOCUMENT_IDS[documentType] },
          title: documentType,
          focused: documentType === "terms",
          versionId: "v1",
          chunksCount: null,
          html: rosterHtml(documentType, 30),
        })),
      ),
      startChat,
    } as unknown as NonNullable<Parameters<typeof startPolicySynchronizedEdit>[1]>;

    const started = await startPolicySynchronizedEdit(
      { sessionId: "session-1", documentIds: DOCUMENT_IDS, changeSet },
      client,
    );

    // Every started job is pinned via document_id — no unpinned multi-document
    // request is ever sent, closing the gap documented in SUPERDOCS_ISSUES.md.
    expect(startChat).toHaveBeenCalledTimes(2);
    expect(startChat.mock.calls.every(([input]) => Boolean(input.documentId))).toBe(true);
    expect(started.jobs.map((targeted) => targeted.documentType)).toEqual([
      "terms",
      "returns",
    ]);
    expect(started.jobs[0].job.jobId).toBe(`job-${DOCUMENT_IDS.terms}`);
    expect(started.jobs[1].job.jobId).toBe(`job-${DOCUMENT_IDS.returns}`);

    const [termsCall, returnsCall] = startChat.mock.calls;
    expect(termsCall[0].documentId).toBe(DOCUMENT_IDS.terms);
    expect(termsCall[0].message).toContain(
      "return window in Terms of Service",
    );
    expect(termsCall[0].message).toContain("Do not modify Returns Policy.");
    expect(returnsCall[0].documentId).toBe(DOCUMENT_IDS.returns);
    expect(returnsCall[0].message).toContain(
      "return window in Returns Policy",
    );
    expect(returnsCall[0].message).toContain("Do not modify Terms of Service.");
  });

  it("denies every pending change on a targeted job when its own batch is polluted with foreign-document proposals", async () => {
    const workspace = generatePolicyWorkspace(NORTHSTAR_GOODS_PROFILE);
    const changeSet = unwrap(proposeReturnWindowChangeSet(workspace, 14));
    const evidenceDirectory = mkdtempSync(
      join(tmpdir(), "policyset-polluted-evidence-"),
    );
    const submitReview = vi.fn(async () => ({
      status: "completed",
      batchComplete: true,
    }));
    const client = {
      getJob: vi.fn(async () => ({
        reference: {
          jobId: "job-terms",
          sessionId: "session-1",
          status: "awaiting_approval" as const,
        },
        progress: 100,
        awaitingKind: null,
        pendingChanges: [
          pendingChange("change-terms", DOCUMENT_IDS.terms),
          pendingChange("change-returns", DOCUMENT_IDS.returns),
          pendingChange("change-privacy", DOCUMENT_IDS.privacy),
        ],
        errorCode: null,
      })),
      submitReview,
    } as unknown as NonNullable<
      Parameters<typeof getPolicyTargetedSynchronizedJob>[1]
    >;

    await expect(
      getPolicyTargetedSynchronizedJob(
        {
          jobId: "job-terms",
          sessionId: "session-1",
          documentType: "terms",
          documentIds: DOCUMENT_IDS,
          changeSet,
        },
        client,
        { evidenceDirectory },
      ),
    ).rejects.toBeInstanceOf(PolicySetSuperDocsSafetyError);
    expect(submitReview).toHaveBeenCalledWith({
      sessionId: "session-1",
      jobId: "job-terms",
      decisions: [
        { changeId: "change-terms", approved: false },
        { changeId: "change-returns", approved: false },
        { changeId: "change-privacy", approved: false },
      ],
    });
    expect(workspace.profile.returns.windowDays).toBe(30);
  });

  it("denies every pending change on a targeted job when the user rejects (per job)", async () => {
    const changeSet = returnWindowChangeSet();
    const evidenceDirectory = mkdtempSync(
      join(tmpdir(), "policyset-reject-evidence-"),
    );
    const submitReview = vi.fn(async () => ({
      status: "completed",
      batchComplete: true,
    }));
    const client = {
      getJob: vi.fn(async () => ({
        reference: {
          jobId: "job-returns",
          sessionId: "session-1",
          status: "awaiting_approval" as const,
        },
        progress: 100,
        awaitingKind: null,
        pendingChanges: [
          returnsFactProposal(),
          returnsBodyProposal(),
        ],
        errorCode: null,
      })),
      submitReview,
    } as unknown as NonNullable<
      Parameters<typeof submitPolicyTargetedSynchronizedReview>[1]
    >;

    const review = await submitPolicyTargetedSynchronizedReview(
      {
        jobId: "job-returns",
        sessionId: "session-1",
        documentType: "returns",
        documentIds: DOCUMENT_IDS,
        changeSet,
        approved: false,
      },
      client,
      { evidenceDirectory },
    );

    // Approved:false is submitted without re-running the gate, matching the
    // reject path: every pending change_id on THIS job is denied outright.
    // The caller (WorkspaceView) does this for every job in the batch.
    expect(submitReview).toHaveBeenCalledWith({
      sessionId: "session-1",
      jobId: "job-returns",
      decisions: [
        { changeId: "change-returns-fact", approved: false },
        { changeId: "change-returns-body", approved: false },
      ],
    });
    expect(review.decisionCount).toBe(2);
  });

  it("keeps the canonical profile at 30 when the update is rejected", () => {
    const workspace = generatePolicyWorkspace(NORTHSTAR_GOODS_PROFILE);
    const changeSet = unwrap(proposeReturnWindowChangeSet(workspace, 14));
    const rejected = unwrap(
      rejectSynchronizedChangeSet(workspace, changeSet),
    );

    expect(rejected.changeSet.status).toBe("rejected");
    expect(rejected.workspace).toBe(workspace);
    expect(rejected.workspace.profile.returns.windowDays).toBe(30);
  });

  it("commits the canonical profile to 14 after a successful validated flow", () => {
    const workspace = generatePolicyWorkspace(NORTHSTAR_GOODS_PROFILE);
    const proposed = unwrap(proposeReturnWindowChangeSet(workspace, 14));
    const approved = unwrap(approveSynchronizedChangeSet(proposed));
    const nextProfile = applyManagedField(
      workspace.profile,
      "returns.windowDays",
      14,
    );
    const before = contentState(renderPolicySet(workspace.profile));
    const afterDocuments = renderPolicySet(nextProfile);
    const completed = unwrap(
      commitValidatedSynchronizedChange(
        workspace,
        approved,
        before,
        documentViews(afterDocuments, before),
        DOCUMENT_IDS,
      ),
    );

    expect(completed.workspace.profile).not.toBe(workspace.profile);
    expect(completed.workspace.profile.returns.windowDays).toBe(14);
    expect(workspace.profile.returns.windowDays).toBe(30);
    expect(completed.unchangedDocuments).toEqual(["privacy", "warranty"]);
  });

  it("blocks canonical commit when Privacy or Warranty drifts", () => {
    const workspace = generatePolicyWorkspace(NORTHSTAR_GOODS_PROFILE);
    const proposed = unwrap(proposeReturnWindowChangeSet(workspace, 14));
    const approved = unwrap(approveSynchronizedChangeSet(proposed));
    const nextProfile = applyManagedField(
      workspace.profile,
      "returns.windowDays",
      14,
    );
    const before = contentState(renderPolicySet(workspace.profile));
    const drifted = renderPolicySet(nextProfile);
    drifted.privacy = `${drifted.privacy}<p>Unexpected privacy drift</p>`;
    const post = documentViews(drifted, before).map((document) =>
      document.documentId === DOCUMENT_IDS.privacy
        ? {
            ...document,
            normalizedContent: `${document.normalizedContent} drift`,
            sha256: "privacy-drifted",
          }
        : document,
    );

    const result = commitValidatedSynchronizedChange(
      workspace,
      approved,
      before,
      post,
      DOCUMENT_IDS,
    );

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.code).toBe("POST_EDIT_VALIDATION_FAILED");
      expect(result.error.message).toContain("privacy");
    }
    expect(workspace.profile.returns.windowDays).toBe(30);
  });

  it("never commits the canonical profile on partial apply (one targeted job's edit never actually landed)", () => {
    const workspace = generatePolicyWorkspace(NORTHSTAR_GOODS_PROFILE);
    const proposed = unwrap(proposeReturnWindowChangeSet(workspace, 14));
    const approved = unwrap(approveSynchronizedChangeSet(proposed));
    const nextProfile = applyManagedField(
      workspace.profile,
      "returns.windowDays",
      14,
    );
    const before = contentState(renderPolicySet(workspace.profile));
    const updated = renderPolicySet(nextProfile);
    const stale = renderPolicySet(workspace.profile);

    // Terms' targeted job completed and applied the 30 -> 14 edit; Returns'
    // targeted job never actually landed its edit (e.g. it failed after
    // Terms' job already succeeded). Two SuperDocs jobs are not one atomic
    // transaction, so this is a real possible post-approval state.
    const post = POLICY_DOCUMENT_TYPES.map((documentType) => {
      const applied = documentType !== "returns";
      return {
        documentId: DOCUMENT_IDS[documentType],
        title: documentType,
        html: applied ? updated[documentType] : stale[documentType],
        normalizedContent: applied
          ? `${updated[documentType]} normalized`
          : before[documentType].normalizedContent,
        sha256: applied ? `${documentType}-updated` : before[documentType].sha256,
      };
    });

    const result = commitValidatedSynchronizedChange(
      workspace,
      approved,
      before,
      post,
      DOCUMENT_IDS,
    );

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.code).toBe("POST_EDIT_VALIDATION_FAILED");
    }
    expect(workspace.profile.returns.windowDays).toBe(30);
    expect(NORTHSTAR_GOODS_PROFILE.returns.windowDays).toBe(30);
  });
});

describe("Phase 5 proposal evidence and structural target safety", () => {
  it("allows a normal body 30 to 14 proposal even when full HTML contains footer text", () => {
    const changeSet = returnWindowChangeSet();
    const proposals = [
      bodyProposal("change-terms", DOCUMENT_IDS.terms),
      bodyProposal("change-returns", DOCUMENT_IDS.returns),
    ];

    expect(() =>
      assertSynchronizedProposalSafety(
        proposals,
        changeSet,
        DOCUMENT_IDS,
      ),
    ).not.toThrow();
  });

  it("fails closed for an actual footer proposal identified by chunk identity", () => {
    const changeSet = returnWindowChangeSet();
    const footer = {
      ...bodyProposal("change-terms", DOCUMENT_IDS.terms),
      chunkId: "footer-default",
    };

    expect(() =>
      assertSynchronizedProposalSafety(
        [footer, bodyProposal("change-returns", DOCUMENT_IDS.returns)],
        changeSet,
        DOCUMENT_IDS,
      ),
    ).toThrow(/chunk_id structurally identifies a footer target/);
  });

  it("fails closed for an actual header proposal identified by structural metadata", () => {
    const changeSet = returnWindowChangeSet();
    const header = {
      ...pendingChange("change-terms", DOCUMENT_IDS.terms),
      chunkId: "chunk-terms-1",
      oldHtml:
        '<div data-part-type="header"><p>Return within 30 days.</p></div>',
      newHtml:
        '<div data-part-type="header"><p>Return within 14 days.</p></div>',
    };

    expect(() =>
      assertSynchronizedProposalSafety(
        [header, pendingChange("change-returns", DOCUMENT_IDS.returns)],
        changeSet,
        DOCUMENT_IDS,
      ),
    ).toThrow(/root element structurally identifies a header target/);
  });

  it("persists sanitized proposal evidence before submitting a review decision", async () => {
    const changeSet = returnWindowChangeSet();
    const evidenceDirectory = mkdtempSync(
      join(tmpdir(), "policyset-proposal-evidence-"),
    );
    const proposals = [
      {
        ...pendingChange("change-terms", DOCUMENT_IDS.terms),
        aiExplanation: "Use token sk_notasecret123456 only for this test.",
      },
      pendingChange("change-returns", DOCUMENT_IDS.returns),
    ];
    const submitReview = vi.fn(async () => {
      const files = readdirSync(evidenceDirectory);
      expect(files).toHaveLength(1);
      const raw = readFileSync(join(evidenceDirectory, files[0]), "utf8");
      expect(raw).not.toContain("sk_notasecret123456");
      const evidence = JSON.parse(raw) as {
        proposals: Array<Record<string, unknown>>;
      };
      expect(evidence.proposals).toHaveLength(2);
      expect(evidence.proposals[0]).toMatchObject({
        change_id: "change-terms",
        document_id: DOCUMENT_IDS.terms,
        chunk_id: "body-return-window",
        operation: "edit",
        old_html: proposals[0].oldHtml,
        new_html: proposals[0].newHtml,
        ai_explanation: "Use token [REDACTED_SECRET] only for this test.",
        local_classification: "body",
      });
      expect(evidence.proposals[0].local_reason).toEqual(expect.any(String));
      return { status: "completed", batchComplete: true };
    });
    const client = {
      getJob: vi.fn(async () => ({
        reference: {
          jobId: "job-evidence",
          sessionId: "session-1",
          status: "awaiting_approval" as const,
        },
        progress: 100,
        awaitingKind: null,
        pendingChanges: proposals,
        errorCode: null,
      })),
      submitReview,
    } as unknown as NonNullable<
      Parameters<typeof submitPolicyTargetedSynchronizedReview>[1]
    >;

    await submitPolicyTargetedSynchronizedReview(
      {
        jobId: "job-evidence",
        sessionId: "session-1",
        documentType: "terms",
        documentIds: DOCUMENT_IDS,
        changeSet,
        approved: false,
      },
      client,
      { evidenceDirectory },
    );

    expect(submitReview).toHaveBeenCalledOnce();
  });
});

describe("Phase 5 managed-fact coverage gate", () => {
  it("rejects a batch that leaves a required Terms occurrence untouched", () => {
    const changeSet = returnWindowChangeSet();
    const proposals = [
      termsFactProposal(),
      returnsFactProposal(),
      returnsBodyProposal(),
    ];

    expect(() =>
      assertSynchronizedProposalCoverage(
        proposals,
        changeSet,
        DOCUMENT_IDS,
        rosterDocuments(30),
      ),
    ).toThrow(/no proposal covers terms: the body prose/);
  });

  it("rejects a batch that leaves a required Returns occurrence untouched", () => {
    const changeSet = returnWindowChangeSet();
    const proposals = [termsFactProposal(), termsBodyProposal()];

    expect(() =>
      assertSynchronizedProposalCoverage(
        proposals,
        changeSet,
        DOCUMENT_IDS,
        rosterDocuments(30),
      ),
    ).toThrow(/no proposal covers returns: the body prose/);
  });

  it("accepts a batch that covers every required occurrence in both documents", () => {
    const changeSet = returnWindowChangeSet();
    const proposals = fullCoverageProposals();

    expect(() =>
      assertSynchronizedProposalCoverage(
        proposals,
        changeSet,
        DOCUMENT_IDS,
        rosterDocuments(30),
      ),
    ).not.toThrow();
  });

  it("does not let a no-op proposal (old_html === new_html) satisfy coverage, even when required occurrences are otherwise fully covered", () => {
    const changeSet = returnWindowChangeSet();
    // Mirrors the observed live-run bug: SuperDocs padded a batch with
    // "edit" proposals whose old_html/new_html were byte-identical, on
    // chunks unrelated to the return window (see SUPERDOCS_ISSUES.md).
    const noOpProposal = chunkProposal(
      "change-terms-title-noop",
      DOCUMENT_IDS.terms,
      "terms-title",
      "Terms of Service",
      "Terms of Service",
    );
    const proposals = [...fullCoverageProposals(), noOpProposal];

    expect(() =>
      assertSynchronizedProposalCoverage(
        proposals,
        changeSet,
        DOCUMENT_IDS,
        rosterDocuments(30),
      ),
    ).toThrow(/holds no required 30-day return-window occurrence/);
  });

  it("still fails closed on polluted targeting even with full coverage", async () => {
    const changeSet = returnWindowChangeSet();
    const proposals = [
      ...fullCoverageProposals(),
      chunkProposal(
        "change-privacy",
        DOCUMENT_IDS.privacy,
        "privacy-body",
        "Data is retained within 30 days of delivery.",
        "Data is retained within 14 days of delivery.",
      ),
    ];

    await expect(
      assertSynchronizedProposalGate(
        {
          sessionId: "session-1",
          pendingChanges: proposals,
          changeSet,
          documentIds: DOCUMENT_IDS,
        },
        rosterClient(30),
      ),
    ).rejects.toThrow(/did not exactly cover every affected PolicySet document/);
  });

  it("denies every change_id on a targeted job and keeps the canonical profile at 30 on incomplete coverage", async () => {
    const workspace = generatePolicyWorkspace(NORTHSTAR_GOODS_PROFILE);
    const changeSet = unwrap(proposeReturnWindowChangeSet(workspace, 14));
    const evidenceDirectory = mkdtempSync(
      join(tmpdir(), "policyset-coverage-evidence-"),
    );
    // Terms' own pinned job updated the "within N days of delivery" prose
    // but left the "N-day window" cross-reference stale — an incomplete
    // batch within a single targeted document.
    const proposals = [termsBodyPartialProposal()];
    const submitReview = vi.fn(async () => ({
      status: "completed",
      batchComplete: true,
    }));
    const client = {
      ...rosterClient(30),
      getJob: vi.fn(async () => ({
        reference: {
          jobId: "job-terms-coverage",
          sessionId: "session-1",
          status: "awaiting_approval" as const,
        },
        progress: 100,
        awaitingKind: null,
        pendingChanges: proposals,
        errorCode: null,
      })),
      submitReview,
    } as unknown as NonNullable<
      Parameters<typeof getPolicyTargetedSynchronizedJob>[1]
    >;

    await expect(
      getPolicyTargetedSynchronizedJob(
        {
          jobId: "job-terms-coverage",
          sessionId: "session-1",
          documentType: "terms",
          documentIds: DOCUMENT_IDS,
          changeSet,
        },
        client,
        { evidenceDirectory },
      ),
    ).rejects.toThrow(/Coverage gate blocked the batch/);
    expect(submitReview).toHaveBeenCalledWith({
      sessionId: "session-1",
      jobId: "job-terms-coverage",
      decisions: [{ changeId: "change-terms-body-partial", approved: false }],
    });
    expect(workspace.profile.returns.windowDays).toBe(30);
    expect(NORTHSTAR_GOODS_PROFILE.returns.windowDays).toBe(30);
  });
});

function chunkProposal(
  changeId: string,
  documentId: string,
  chunkId: string,
  oldText: string,
  newText: string,
): PendingChange {
  return {
    changeId,
    operation: "edit",
    documentId,
    chunkId,
    oldHtml: `<p data-chunk-id="${chunkId}">${oldText}</p>`,
    newHtml: `<p data-chunk-id="${chunkId}">${newText}</p>`,
    aiExplanation: "Update the managed return window.",
  };
}

/** An unrelated proposal in the same batch — no return-window occurrence. */
function termsFactProposal(): PendingChange {
  return chunkProposal(
    "change-terms-fact",
    DOCUMENT_IDS.terms,
    "terms-fact-name",
    "<strong>Legal name: </strong>Northstar Goods",
    "<strong>Legal name: </strong>Northstar Goods",
  );
}

function termsBodyProposal(): PendingChange {
  return chunkProposal(
    "change-terms-body",
    DOCUMENT_IDS.terms,
    "terms-body-returns",
    TERMS_BODY_TEXT(30),
    TERMS_BODY_TEXT(14),
  );
}

/**
 * Updates the "within N days of delivery" prose to the next value and drops
 * the stale value everywhere, so the coarse safety check passes, but never
 * introduces the new "N-day window" cross-reference — an incomplete update
 * within one chunk that only the finer-grained coverage gate catches.
 */
function termsBodyPartialProposal(): PendingChange {
  return chunkProposal(
    "change-terms-body-partial",
    DOCUMENT_IDS.terms,
    "terms-body-returns",
    TERMS_BODY_TEXT(30),
    "Eligible items may be returned within 14 days of delivery if they are unused, in original packaging, and accompanied by proof of purchase. The Returns Policy states the same return window and the full process.",
  );
}

/** An unrelated proposal in the same batch — no return-window occurrence. */
function returnsFactProposal(): PendingChange {
  return chunkProposal(
    "change-returns-fact",
    DOCUMENT_IDS.returns,
    "returns-fact-processing",
    "<strong>Refund processing (days): </strong>7",
    "<strong>Refund processing (days): </strong>7",
  );
}

function returnsBodyProposal(): PendingChange {
  return chunkProposal(
    "change-returns-body",
    DOCUMENT_IDS.returns,
    "returns-body-window",
    RETURNS_BODY_TEXT(30),
    RETURNS_BODY_TEXT(14),
  );
}

function fullCoverageProposals(): PendingChange[] {
  return [termsBodyProposal(), returnsBodyProposal()];
}

function TERMS_BODY_TEXT(windowDays: number): string {
  return `Eligible items may be returned within ${windowDays} days of delivery if they are unused, in original packaging, and accompanied by proof of purchase. The Returns Policy states the same ${windowDays}-day window and the full process.`;
}

function RETURNS_BODY_TEXT(windowDays: number): string {
  return `You may return eligible items within ${windowDays} days of delivery. This ${windowDays}-day window is the same return window stated in our Terms of Service.`;
}

/** Mirrors the chunked shape of authoritative SuperDocs roster HTML. */
function rosterHtml(
  documentType: PolicyDocumentType,
  windowDays: number,
): string {
  const parts: string[] = [];
  if (documentType === "terms") {
    parts.push(
      '<h1 data-chunk-id="terms-title">Terms of Service</h1>',
      '<p data-chunk-id="terms-fact-name"><strong>Legal name: </strong>Northstar Goods</p>',
      '<h2 data-chunk-id="terms-heading-returns">Returns</h2>',
      `<p data-chunk-id="terms-body-returns">${TERMS_BODY_TEXT(windowDays)}</p>`,
      '<p data-chunk-id="terms-body-warranty">Goods include a 12-month limited warranty against manufacturing defects.</p>',
    );
  } else if (documentType === "returns") {
    parts.push(
      '<h1 data-chunk-id="returns-title">Returns Policy</h1>',
      '<p data-chunk-id="returns-fact-processing"><strong>Refund processing (days): </strong>7</p>',
      '<h2 data-chunk-id="returns-heading-window">Return window</h2>',
      `<p data-chunk-id="returns-body-window">${RETURNS_BODY_TEXT(windowDays)}</p>`,
      '<p data-chunk-id="returns-body-refunds">Approved refunds are issued via original payment method within 7 days after we receive and inspect the return.</p>',
    );
  } else {
    parts.push(
      `<h1 data-chunk-id="${documentType}-title">${documentType}</h1>`,
      `<p data-chunk-id="${documentType}-body">Unrelated managed content.</p>`,
    );
  }

  parts.push(
    `<header data-chunk-id="${documentType}-header" data-part-type="header"><p>Northstar Goods</p></header>`,
    `<footer data-chunk-id="${documentType}-footer" data-part-type="footer"><p>drafted for attorney review, not legal advice</p></footer>`,
  );
  return parts.join("\n");
}

function rosterDocuments(
  windowDays: number,
): SuperDocsSessionDocumentView[] {
  return POLICY_DOCUMENT_TYPES.map((documentType) => ({
    documentId: DOCUMENT_IDS[documentType],
    title: documentType,
    html: rosterHtml(documentType, windowDays),
    normalizedContent: rosterHtml(documentType, windowDays),
    sha256: `${documentType}-${windowDays}`,
  }));
}

function rosterClient(windowDays: number) {
  return {
    listSessionDocuments: vi.fn(async (sessionId: string) =>
      POLICY_DOCUMENT_TYPES.map((documentType) => ({
        identity: { sessionId, documentId: DOCUMENT_IDS[documentType] },
        title: documentType,
        focused: documentType === "terms",
        versionId: "v1",
        chunksCount: null,
        html: rosterHtml(documentType, windowDays),
      })),
    ),
  } as unknown as NonNullable<
    Parameters<typeof assertSynchronizedProposalGate>[1]
  >;
}

function pendingChange(changeId: string, documentId: string) {
  return {
    changeId,
    operation: "edit" as const,
    documentId,
    chunkId: "body-return-window",
    oldHtml: "<p>Eligible items may be returned within 30 days of delivery.</p>",
    newHtml: "<p>Eligible items may be returned within 14 days of delivery.</p>",
    aiExplanation: "Update the managed return window.",
  };
}

function bodyProposal(
  changeId: string,
  documentId: string,
): PendingChange {
  return {
    ...pendingChange(changeId, documentId),
    oldHtml:
      "<article><h1>Returns</h1><p>Eligible items may be returned within 30 days of delivery.</p><footer>drafted for attorney review, not legal advice</footer></article>",
    newHtml:
      "<article><h1>Returns</h1><p>Eligible items may be returned within 14 days of delivery.</p><footer>drafted for attorney review, not legal advice</footer></article>",
  };
}

function returnWindowChangeSet() {
  const workspace = generatePolicyWorkspace(NORTHSTAR_GOODS_PROFILE);
  return unwrap(proposeReturnWindowChangeSet(workspace, 14));
}

function contentState(
  documents: PolicyDocumentSet,
): PolicyDocumentContentStateMap {
  const state = {} as PolicyDocumentContentStateMap;
  for (const documentType of POLICY_DOCUMENT_TYPES) {
    state[documentType] = {
      documentId: DOCUMENT_IDS[documentType],
      normalizedContent: documents[documentType],
      sha256: `${documentType}-unchanged`,
    };
  }
  return state;
}

function documentViews(
  documents: PolicyDocumentSet,
  before: PolicyDocumentContentStateMap,
): SuperDocsSessionDocumentView[] {
  return POLICY_DOCUMENT_TYPES.map((documentType) => {
    const affected = documentType === "terms" || documentType === "returns";
    return {
      documentId: DOCUMENT_IDS[documentType],
      title: documentType,
      html: documents[documentType],
      normalizedContent: affected
        ? `${documents[documentType]} normalized`
        : before[documentType].normalizedContent,
      sha256: affected
        ? `${documentType}-updated`
        : before[documentType].sha256,
    };
  });
}

function unwrap<T>(result: Result<T>): T {
  if (!result.ok) {
    throw new Error(`${result.error.code}: ${result.error.message}`);
  }
  return result.value;
}

describe("Phase 5 session-lock experiment preparation", () => {
  it("preserves the HTTP status, request id, and sanitized provider code/detail of a rejected chat start", async () => {
    const client = new SuperDocsClient({
      apiKey: "test-key",
      fetch: (async () =>
        new Response(
          JSON.stringify({
            error: {
              code: "job_in_flight",
              detail:
                "A chat job is already running on this session. api_key=sk_live_abcdefgh12345678 must not survive.",
            },
          }),
          {
            status: 409,
            headers: {
              "Content-Type": "application/json",
              "X-Request-ID": "req-abc-123",
            },
          },
        )) as unknown as typeof fetch,
    });

    const error = await client
      .startChat({ sessionId: "session-1", documentId: "doc-returns", message: "edit" })
      .then(
        () => null,
        (caught: unknown) => caught,
      );

    expect(error).toBeInstanceOf(SuperDocsRequestError);
    const diagnostics = (error as SuperDocsRequestError).diagnostics();
    expect(diagnostics.statusCode).toBe(409);
    expect(diagnostics.requestId).toBe("req-abc-123");
    expect(diagnostics.providerCode).toBe("job_in_flight");
    expect(diagnostics.providerDetail).toContain("already running on this session");
    // Secrets never survive into retained diagnostics.
    expect(diagnostics.providerDetail).not.toContain("sk_live_abcdefgh12345678");
    expect(diagnostics.providerDetail).toContain("[REDACTED]");
    // The friendly application message is unchanged.
    expect((error as SuperDocsRequestError).message).toBe(
      "SuperDocs rejected the operation for the current job state",
    );
  });

  it("preserves an already-started targeted job when a later targeted start fails", async () => {
    const workspace = generatePolicyWorkspace(NORTHSTAR_GOODS_PROFILE);
    const changeSet = unwrap(proposeReturnWindowChangeSet(workspace, 14));
    const startChat = vi.fn(async (input: { documentId?: string; sessionId: string }) => {
      if (input.documentId === DOCUMENT_IDS.returns) {
        throw new SuperDocsRequestError(
          "SuperDocs rejected the operation for the current job state",
          {
            statusCode: 409,
            requestId: "req-second-start",
            providerCode: "job_in_flight",
          },
        );
      }
      return {
        jobId: "job-terms",
        sessionId: input.sessionId,
        status: "in_progress" as const,
      };
    });
    const client = {
      ...rosterClient(30),
      startChat,
    } as unknown as NonNullable<Parameters<typeof startPolicySynchronizedEdit>[1]>;

    const error = await startPolicySynchronizedEdit(
      { sessionId: "session-1", documentIds: DOCUMENT_IDS, changeSet },
      client,
    ).then(
      () => null,
      (caught: unknown) => caught,
    );

    expect(error).toBeInstanceOf(PolicySetSynchronizedStartError);
    const startError = error as PolicySetSynchronizedStartError;
    expect(startError.failedDocumentType).toBe("returns");
    expect(startError.successfullyStartedJobs).toHaveLength(1);
    expect(startError.successfullyStartedJobs[0].documentType).toBe("terms");
    expect(startError.successfullyStartedJobs[0].job.jobId).toBe("job-terms");
    expect(startError.requestError?.statusCode).toBe(409);
    expect(startError.requestError?.requestId).toBe("req-second-start");
  });

  it("counts one locally observed successful chat start when the first succeeds and the second fails", async () => {
    const workspace = generatePolicyWorkspace(NORTHSTAR_GOODS_PROFILE);
    const changeSet = unwrap(proposeReturnWindowChangeSet(workspace, 14));
    const startChat = vi.fn(async (input: { documentId?: string; sessionId: string }) => {
      if (input.documentId === DOCUMENT_IDS.returns) {
        throw new SuperDocsRequestError("SuperDocs rejected the operation for the current job state", {
          statusCode: 409,
        });
      }
      return { jobId: "job-terms", sessionId: input.sessionId, status: "in_progress" as const };
    });
    const client = {
      ...rosterClient(30),
      startChat,
    } as unknown as NonNullable<Parameters<typeof startPolicySynchronizedEdit>[1]>;

    const error = (await startPolicySynchronizedEdit(
      { sessionId: "session-1", documentIds: DOCUMENT_IDS, changeSet },
      client,
    ).then(
      () => null,
      (caught: unknown) => caught,
    )) as PolicySetSynchronizedStartError;

    // Counted from what SuperDocs actually accepted, not from a completed
    // batch. The provider returns no usage metadata, so this stays local.
    expect(error.successfullyStartedJobs.length).toBe(1);
    expect(startChat).toHaveBeenCalledTimes(2);
  });

  it("does not attempt the second pinned start until the first job reaches awaiting_approval", async () => {
    const changeSet = returnWindowChangeSet();
    const evidenceDirectory = mkdtempSync(
      join(tmpdir(), "policyset-session-lock-evidence-"),
    );
    const statuses = ["pending", "in_progress", "awaiting_approval"] as const;
    let poll = 0;
    const startChat = vi.fn(async (input: { documentId?: string; sessionId: string }) => ({
      jobId: `job-${input.documentId}`,
      sessionId: input.sessionId,
      status: "pending" as const,
    }));
    const startCallsAtEachPoll: number[] = [];
    const client = {
      ...rosterClient(30),
      startChat,
      getJob: vi.fn(async () => {
        startCallsAtEachPoll.push(startChat.mock.calls.length);
        const status = statuses[Math.min(poll, statuses.length - 1)];
        poll += 1;
        return {
          reference: { jobId: "job-doc-terms", sessionId: "session-1", status },
          progress: null,
          awaitingKind: null,
          pendingChanges:
            status === "awaiting_approval" ? [termsBodyProposal()] : [],
          errorCode: null,
        };
      }),
      submitReview: vi.fn(async () => ({ status: "completed", batchComplete: true })),
    } as unknown as NonNullable<Parameters<typeof runSessionLockExperiment>[1]>;

    const result = await runSessionLockExperiment(
      {
        sessionId: "session-1",
        documentIds: DOCUMENT_IDS,
        changeSet,
        firstDocumentType: "terms",
        secondDocumentType: "returns",
        awaitFirstJobReview: async (pollJob) => {
          let job = await pollJob();
          while (job.status !== "awaiting_approval") {
            job = await pollJob();
          }
          return job;
        },
      },
      client,
      { evidenceDirectory },
    );

    expect(result.outcome).toBe("second_start_accepted");
    // Only the Terms start had been issued while the job was still settling.
    expect(startCallsAtEachPoll).toEqual([1, 1, 1]);
    expect(result.firstJobStatusAtSecondStart).toBe("awaiting_approval");
    expect(startChat).toHaveBeenCalledTimes(2);
    expect(startChat.mock.calls[1][0].documentId).toBe(DOCUMENT_IDS.returns);
    expect(result.locallyObservedSuccessfulChatStarts).toBe(2);
  });

  it("never approves the first job during the experiment and skips the second start when the first gate fails", async () => {
    const changeSet = returnWindowChangeSet();
    const evidenceDirectory = mkdtempSync(
      join(tmpdir(), "policyset-session-lock-gate-"),
    );
    const submitReview = vi.fn(async () => ({ status: "completed", batchComplete: true }));
    const startChat = vi.fn(async (input: { documentId?: string; sessionId: string }) => ({
      jobId: `job-${input.documentId}`,
      sessionId: input.sessionId,
      status: "awaiting_approval" as const,
    }));
    const client = {
      ...rosterClient(30),
      startChat,
      // The delivery-window prose updated but the day-window cross-reference
      // was left stale: coverage fails.
      getJob: vi.fn(async () => ({
        reference: {
          jobId: "job-doc-terms",
          sessionId: "session-1",
          status: "awaiting_approval" as const,
        },
        progress: 100,
        awaitingKind: null,
        pendingChanges: [termsBodyPartialProposal()],
        errorCode: null,
      })),
      submitReview,
    } as unknown as NonNullable<Parameters<typeof runSessionLockExperiment>[1]>;

    const result = await runSessionLockExperiment(
      {
        sessionId: "session-1",
        documentIds: DOCUMENT_IDS,
        changeSet,
        firstDocumentType: "terms",
        secondDocumentType: "returns",
        awaitFirstJobReview: (pollJob) => pollJob(),
      },
      client,
      { evidenceDirectory },
    );

    expect(result.outcome).toBe("first_gate_failed");
    // The Returns start is never paid for once Terms fails its own gate.
    expect(startChat).toHaveBeenCalledTimes(1);
    expect(result.locallyObservedSuccessfulChatStarts).toBe(1);
    // Every decision submitted during the experiment is a denial.
    expect(submitReview).toHaveBeenCalled();
    for (const [call] of submitReview.mock.calls as unknown as [
      { decisions: { approved: boolean }[] },
    ][]) {
      expect(call.decisions.every((decision) => !decision.approved)).toBe(true);
    }
  });
});
